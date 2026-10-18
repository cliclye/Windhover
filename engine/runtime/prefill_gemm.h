/* prefill_gemm.h — register-tiled int8 GEMM for batched prefill (S > 1).
 *
 * The decode GEMV (mm_wt) walks one weight row against every token with a
 * full horizontal reduction per (row, token) and, for int4 rows, re-unpacks
 * the nibbles once per token. That is fine at S=1 but leaves prefill ~10x
 * below what the SDOT units can do. Here:
 *
 *   - 4 weight rows x 4 tokens per micro-tile: 16 SDOT per 8 loads, sums
 *     reduced with a pairwise-add tree (no per-dot ADDV),
 *   - int4-g64 rows are unpacked to signed int8 once per 4-row block and
 *     reused across every token tile,
 *   - down^T (stored [inter][hidden] for the sparse path) is handled by
 *     building a transposed int8 panel per 64-column block, with the per-row
 *     int8 scale folded into the activations, which are re-quantized per
 *     64-wide group (q8 blocks, the same trade llama.cpp makes).
 *
 * All arithmetic stays integer until one float scale per (row, group,
 * token); results match the GEMV path to float rounding.
 * Included from windhover.c after WT / mm_wt are defined.
 */
#ifndef WH_PREFILL_GEMM_H
#define WH_PREFILL_GEMM_H

#if defined(__ARM_NEON) && defined(__ARM_FEATURE_DOTPROD)
#define WH_HAVE_TILED_PREFILL 1

/* Shared scratch for transposed per-group activation terms, grown on demand.
 * Written before the parallel region, read-only inside it. */
static float *g_pf_xsT;      /* [S/4][ng][4]  float(xqsum) or group scale */
static int64_t g_pf_xsT_cap;
static int8_t *g_pf_wbuf;     /* per-thread unpack / panel scratch */
static int64_t g_pf_wbuf_per;
static int g_pf_wbuf_nth;

static float *pf_xsT(int64_t n) {
    if (n > g_pf_xsT_cap) {
        free(g_pf_xsT);
        g_pf_xsT = (float *)malloc((size_t)n * sizeof(float));
        if (!g_pf_xsT) { fprintf(stderr, "[wh] OOM prefill scratch\n"); exit(1); }
        g_pf_xsT_cap = n;
    }
    return g_pf_xsT;
}

/* Grow the per-thread scratch. Call OUTSIDE any parallel region. */
static void pf_wbuf_reserve(int nth, int64_t per) {
    if (per <= g_pf_wbuf_per && nth <= g_pf_wbuf_nth) return;
    free(g_pf_wbuf);
    int64_t p = per > g_pf_wbuf_per ? per : g_pf_wbuf_per;
    int n = nth > g_pf_wbuf_nth ? nth : g_pf_wbuf_nth;
    p = (p + 63) / 64 * 64;
    g_pf_wbuf = (int8_t *)aligned_alloc(64, (size_t)(p * n));
    if (!g_pf_wbuf) { fprintf(stderr, "[wh] OOM prefill wbuf\n"); exit(1); }
    g_pf_wbuf_per = p;
    g_pf_wbuf_nth = n;
}

static inline int8_t *pf_wbuf(int tid) {
    return g_pf_wbuf + (int64_t)tid * g_pf_wbuf_per;
}

/* 4 rows x 4 tokens int8 dot over K (K % 16 == 0).
 * out[r] = { dot(w_r, x_0), dot(w_r, x_1), dot(w_r, x_2), dot(w_r, x_3) }. */
static inline void pf_dot4x4(const int8_t *w0, const int8_t *w1,
                             const int8_t *w2, const int8_t *w3,
                             const int8_t *x0, const int8_t *x1,
                             const int8_t *x2, const int8_t *x3,
                             int K, int32x4_t out[4]) {
    int32x4_t a00 = vdupq_n_s32(0), a01 = a00, a02 = a00, a03 = a00;
    int32x4_t a10 = a00, a11 = a00, a12 = a00, a13 = a00;
    int32x4_t a20 = a00, a21 = a00, a22 = a00, a23 = a00;
    int32x4_t a30 = a00, a31 = a00, a32 = a00, a33 = a00;
    for (int k = 0; k < K; k += 16) {
        int8x16_t X0 = vld1q_s8(x0 + k), X1 = vld1q_s8(x1 + k);
        int8x16_t X2 = vld1q_s8(x2 + k), X3 = vld1q_s8(x3 + k);
        int8x16_t W = vld1q_s8(w0 + k);
        a00 = vdotq_s32(a00, W, X0); a01 = vdotq_s32(a01, W, X1);
        a02 = vdotq_s32(a02, W, X2); a03 = vdotq_s32(a03, W, X3);
        W = vld1q_s8(w1 + k);
        a10 = vdotq_s32(a10, W, X0); a11 = vdotq_s32(a11, W, X1);
        a12 = vdotq_s32(a12, W, X2); a13 = vdotq_s32(a13, W, X3);
        W = vld1q_s8(w2 + k);
        a20 = vdotq_s32(a20, W, X0); a21 = vdotq_s32(a21, W, X1);
        a22 = vdotq_s32(a22, W, X2); a23 = vdotq_s32(a23, W, X3);
        W = vld1q_s8(w3 + k);
        a30 = vdotq_s32(a30, W, X0); a31 = vdotq_s32(a31, W, X1);
        a32 = vdotq_s32(a32, W, X2); a33 = vdotq_s32(a33, W, X3);
    }
    out[0] = vpaddq_s32(vpaddq_s32(a00, a01), vpaddq_s32(a02, a03));
    out[1] = vpaddq_s32(vpaddq_s32(a10, a11), vpaddq_s32(a12, a13));
    out[2] = vpaddq_s32(vpaddq_s32(a20, a21), vpaddq_s32(a22, a23));
    out[3] = vpaddq_s32(vpaddq_s32(a30, a31), vpaddq_s32(a32, a33));
}

/* Same tile, two activation planes: out = 254 * dot(w, hi) + dot(w, lo).
 * The hi accumulators are scaled in-register before the lo pass so the
 * 4x4 tile is reduced once (|hi-dot| <= 64*127*127, x254 fits int32). */
static inline void pf_dot4x4_hilo(const int8_t *w0, const int8_t *w1,
                                  const int8_t *w2, const int8_t *w3,
                                  const int8_t *const hx[4], const int8_t *const lx[4],
                                  int K, int32x4_t out[4]) {
    int32x4_t a[4][4];
    for (int r = 0; r < 4; r++)
        for (int t = 0; t < 4; t++) a[r][t] = vdupq_n_s32(0);
    const int8_t *wr[4] = {w0, w1, w2, w3};
    for (int pass = 0; pass < 2; pass++) {
        const int8_t *const *xs = pass ? lx : hx;
        if (pass)
            for (int r = 0; r < 4; r++)
                for (int t = 0; t < 4; t++) a[r][t] = vmulq_n_s32(a[r][t], 254);
        for (int k = 0; k < K; k += 16) {
            int8x16_t X0 = vld1q_s8(xs[0] + k), X1 = vld1q_s8(xs[1] + k);
            int8x16_t X2 = vld1q_s8(xs[2] + k), X3 = vld1q_s8(xs[3] + k);
            for (int r = 0; r < 4; r++) {
                int8x16_t W = vld1q_s8(wr[r] + k);
                a[r][0] = vdotq_s32(a[r][0], W, X0);
                a[r][1] = vdotq_s32(a[r][1], W, X1);
                a[r][2] = vdotq_s32(a[r][2], W, X2);
                a[r][3] = vdotq_s32(a[r][3], W, X3);
            }
        }
    }
    for (int r = 0; r < 4; r++)
        out[r] = vpaddq_s32(vpaddq_s32(a[r][0], a[r][1]), vpaddq_s32(a[r][2], a[r][3]));
}

/* Unpack one int4-g64 row (stored q+8, low nibble first) to signed int8. */
static inline void pf_unpack_i4_row(const uint8_t *w4, int8_t *dst, int I) {
    const uint8x16_t m4 = vdupq_n_u8(0x0F);
    const int8x16_t b8 = vdupq_n_s8(8);
    for (int i = 0; i < I; i += 32) {
        uint8x16_t by = vld1q_u8(w4 + (i >> 1));
        uint8x16x2_t z = vzipq_u8(vandq_u8(by, m4), vshrq_n_u8(by, 4));
        vst1q_s8(dst + i, vsubq_s8(vreinterpretq_s8_u8(z.val[0]), b8));
        vst1q_s8(dst + i + 16, vsubq_s8(vreinterpretq_s8_u8(z.val[1]), b8));
    }
}

static inline void pf_store4(float *y, int64_t ystride, int s0, int o, float32x4_t v) {
    y[(int64_t)(s0 + 0) * ystride + o] = vgetq_lane_f32(v, 0);
    y[(int64_t)(s0 + 1) * ystride + o] = vgetq_lane_f32(v, 1);
    y[(int64_t)(s0 + 2) * ystride + o] = vgetq_lane_f32(v, 2);
    y[(int64_t)(s0 + 3) * ystride + o] = vgetq_lane_f32(v, 3);
}

/* Tiled body of mm_wt for S >= 4. Covers rows [0, O4) x tokens [0, S4);
 * caller handles the ragged edges with the GEMV path. Inside omp parallel. */
static void pf_mm_tiles(const WT *w, const int8_t *xq, const float *sx,
                        const float *xsT, float *y, int S4, int O4, int ystride) {
    int I = w->I, ng = w->ng;
    int tid = 0;
#ifdef _OPENMP
    tid = omp_get_thread_num();
#endif
    int8_t *ub = (w->fmt == WT_I4G) ? pf_wbuf(tid) : NULL;
    #pragma omp for schedule(static) nowait
    for (int o0 = 0; o0 < O4; o0 += 4) {
        const int8_t *wr[4];
        if (w->fmt == WT_I8R) {
            for (int r = 0; r < 4; r++) wr[r] = w->q8 + (int64_t)(o0 + r) * I;
        } else {
            for (int r = 0; r < 4; r++) {
                pf_unpack_i4_row(w->q4 + (int64_t)(o0 + r) * (I >> 1), ub + (int64_t)r * I, I);
                wr[r] = ub + (int64_t)r * I;
            }
        }
        for (int s0 = 0; s0 < S4; s0 += 4) {
            const int8_t *x0 = xq + (int64_t)s0 * I, *x1 = x0 + I, *x2 = x1 + I, *x3 = x2 + I;
            float32x4_t sxv = vld1q_f32(sx + s0);
            if (w->fmt == WT_I8R) {
                int32x4_t r[4];
                pf_dot4x4(wr[0], wr[1], wr[2], wr[3], x0, x1, x2, x3, I, r);
                for (int k = 0; k < 4; k++)
                    pf_store4(y, ystride, s0, o0 + k,
                              vmulq_f32(vmulq_n_f32(vcvtq_f32_s32(r[k]), w->rs[o0 + k]), sxv));
            } else {
                float32x4_t f0 = vdupq_n_f32(0.f), f1 = f0, f2 = f0, f3 = f0;
                const float *xs = xsT + (int64_t)(s0 / 4) * ng * 4;
                const wh_f16 *sc0 = w->sc + (int64_t)o0 * ng, *zp0 = w->zp + (int64_t)o0 * ng;
                for (int g = 0; g < ng; g++) {
                    int32x4_t r[4];
                    int k = g * WH_GS;
                    pf_dot4x4(wr[0] + k, wr[1] + k, wr[2] + k, wr[3] + k,
                              x0 + k, x1 + k, x2 + k, x3 + k, WH_GS, r);
                    float32x4_t xsg = vld1q_f32(xs + g * 4);
                    f0 = vfmaq_n_f32(vfmaq_n_f32(f0, vcvtq_f32_s32(r[0]), (float)sc0[g]),
                                     xsg, (float)zp0[g]);
                    f1 = vfmaq_n_f32(vfmaq_n_f32(f1, vcvtq_f32_s32(r[1]), (float)sc0[ng + g]),
                                     xsg, (float)zp0[ng + g]);
                    f2 = vfmaq_n_f32(vfmaq_n_f32(f2, vcvtq_f32_s32(r[2]), (float)sc0[2 * ng + g]),
                                     xsg, (float)zp0[2 * ng + g]);
                    f3 = vfmaq_n_f32(vfmaq_n_f32(f3, vcvtq_f32_s32(r[3]), (float)sc0[3 * ng + g]),
                                     xsg, (float)zp0[3 * ng + g]);
                }
                pf_store4(y, ystride, s0, o0 + 0, vmulq_f32(f0, sxv));
                pf_store4(y, ystride, s0, o0 + 1, vmulq_f32(f1, sxv));
                pf_store4(y, ystride, s0, o0 + 2, vmulq_f32(f2, sxv));
                pf_store4(y, ystride, s0, o0 + 3, vmulq_f32(f3, sxv));
            }
        }
    }
}

/* Activation group sums, transposed per 4-token tile: xsT[t4][g][lane]. */
static const float *pf_prep_xsum(const int32_t *xqsum, int S4, int ng) {
    float *xsT = pf_xsT((int64_t)S4 * ng);
    for (int s0 = 0; s0 < S4; s0 += 4)
        for (int g = 0; g < ng; g++)
            for (int t = 0; t < 4; t++)
                xsT[((int64_t)(s0 / 4) * ng + g) * 4 + t] =
                    (float)xqsum[(int64_t)(s0 + t) * ng + g];
    return xsT;
}

/* ---- down^T prefill: out[s][d] = sum_j h[s][j] * rs[j] * q8[j][d] -------- */

/* Quantize h'[s][j] = h[s][j]*rs[j] per 64-wide group of j as a two-plane
 * int8 pair: h' ~= sc * (hi + lo/254). A single int8 plane costs ~1% RMS on
 * heavy-tailed FFN activations (KL ~0.1 vs the f32 path); hi+lo is ~15-bit.
 * hq/hl: [S][Li], scT: [S/4][Li/64][4] group scales (transposed per tile). */
static void pf_down_prep(const float *h, int S, int Li, const float *rs,
                         int8_t *hq, int8_t *hl, float *scT, int S4) {
    int ng = Li / WH_GS;
    #pragma omp parallel for schedule(static)
    for (int s = 0; s < S; s++) {
        const float *hr = h + (int64_t)s * Li;
        int8_t *qr = hq + (int64_t)s * Li;
        int8_t *lr = hl + (int64_t)s * Li;
        for (int g = 0; g < ng; g++) {
            float tmp[WH_GS];
            float32x4_t am = vdupq_n_f32(0.f);
            for (int j = 0; j < WH_GS; j += 4) {
                float32x4_t v = vmulq_f32(vld1q_f32(hr + g * WH_GS + j),
                                          vld1q_f32(rs + g * WH_GS + j));
                vst1q_f32(tmp + j, v);
                am = vmaxq_f32(am, vabsq_f32(v));
            }
            float amax = vmaxvq_f32(am);
            float sc = amax > 0.f ? amax / (127.f * 254.f) : 0.f;   /* applied to hi*254+lo */
            float inv = amax > 0.f ? 127.f / amax : 0.f;
            float32x4_t vi = vdupq_n_f32(inv);
            for (int j = 0; j < WH_GS; j += 16) {
                int32x4_t qi[4], li[4];
                for (int u = 0; u < 4; u++) {
                    float32x4_t v = vmulq_f32(vld1q_f32(tmp + j + 4 * u), vi);
                    qi[u] = vcvtnq_s32_f32(v);
                    float32x4_t r = vsubq_f32(v, vcvtq_f32_s32(qi[u]));      /* [-0.5, 0.5] */
                    li[u] = vcvtnq_s32_f32(vmulq_n_f32(r, 254.f));
                }
                int16x8_t a = vcombine_s16(vqmovn_s32(qi[0]), vqmovn_s32(qi[1]));
                int16x8_t b = vcombine_s16(vqmovn_s32(qi[2]), vqmovn_s32(qi[3]));
                vst1q_s8(qr + g * WH_GS + j, vcombine_s8(vqmovn_s16(a), vqmovn_s16(b)));
                a = vcombine_s16(vqmovn_s32(li[0]), vqmovn_s32(li[1]));
                b = vcombine_s16(vqmovn_s32(li[2]), vqmovn_s32(li[3]));
                vst1q_s8(lr + g * WH_GS + j, vcombine_s8(vqmovn_s16(a), vqmovn_s16(b)));
            }
            if (s < S4)
                scT[((int64_t)(s / 4) * ng + g) * 4 + (s & 3)] = sc;
        }
    }
}

/* Transpose a 16x16 int8 block: src rows at stride ss, dst rows at stride ds. */
static inline void pf_tr16(const int8_t *src, int64_t ss, int8_t *dst, int64_t ds) {
    int8x16_t r[16];
    for (int i = 0; i < 16; i++) r[i] = vld1q_s8(src + i * ss);
    int8x16_t t8[16];
    for (int i = 0; i < 16; i += 2) {
        t8[i] = vtrn1q_s8(r[i], r[i + 1]);
        t8[i + 1] = vtrn2q_s8(r[i], r[i + 1]);
    }
    int16x8_t t16[16];
    for (int i = 0; i < 16; i += 4)
        for (int k = 0; k < 2; k++) {
            t16[i + k] = vtrn1q_s16(vreinterpretq_s16_s8(t8[i + k]), vreinterpretq_s16_s8(t8[i + k + 2]));
            t16[i + k + 2] = vtrn2q_s16(vreinterpretq_s16_s8(t8[i + k]), vreinterpretq_s16_s8(t8[i + k + 2]));
        }
    int32x4_t t32[16];
    for (int i = 0; i < 16; i += 8)
        for (int k = 0; k < 4; k++) {
            t32[i + k] = vtrn1q_s32(vreinterpretq_s32_s16(t16[i + k]), vreinterpretq_s32_s16(t16[i + k + 4]));
            t32[i + k + 4] = vtrn2q_s32(vreinterpretq_s32_s16(t16[i + k]), vreinterpretq_s32_s16(t16[i + k + 4]));
        }
    int64x2_t t64[16];
    for (int k = 0; k < 8; k++) {
        t64[k] = vtrn1q_s64(vreinterpretq_s64_s32(t32[k]), vreinterpretq_s64_s32(t32[k + 8]));
        t64[k + 8] = vtrn2q_s64(vreinterpretq_s64_s32(t32[k]), vreinterpretq_s64_s32(t32[k + 8]));
    }
    /* After the four trn stages, t64[c] holds source column c. */
    for (int c = 0; c < 16; c++)
        vst1q_s8(dst + c * ds, vreinterpretq_s8_s64(t64[c]));
}

#define WH_PF_DBLK 64

/* Tiled down^T for d in [0, D) and tokens [0, S4). Inside omp parallel.
 * Panel per thread: [WH_PF_DBLK][Li] int8 (transposed down^T columns). */
static void pf_down_tiles(const WT *w, const int8_t *hq, const int8_t *hl,
                          const float *scT, float *out, int S4, int Li, int D) {
    int ng = Li / WH_GS;
    int tid = 0;
#ifdef _OPENMP
    tid = omp_get_thread_num();
#endif
    int8_t *P = pf_wbuf(tid);
    #pragma omp for schedule(static) nowait
    for (int d0 = 0; d0 < D; d0 += WH_PF_DBLK) {
        for (int j = 0; j < Li; j += 16)
            for (int dd = 0; dd < WH_PF_DBLK; dd += 16)
                pf_tr16(w->q8 + (int64_t)j * D + d0 + dd, D, P + (int64_t)dd * Li + j, Li);
        for (int dr = 0; dr < WH_PF_DBLK; dr += 4) {
            const int8_t *p0 = P + (int64_t)dr * Li, *p1 = p0 + Li, *p2 = p1 + Li, *p3 = p2 + Li;
            for (int s0 = 0; s0 < S4; s0 += 4) {
                const int8_t *x0 = hq + (int64_t)s0 * Li, *x1 = x0 + Li, *x2 = x1 + Li, *x3 = x2 + Li;
                const int8_t *l0 = hl + (int64_t)s0 * Li, *l1 = l0 + Li, *l2 = l1 + Li, *l3 = l2 + Li;
                const float *sc = scT + (int64_t)(s0 / 4) * ng * 4;
                float32x4_t f0 = vdupq_n_f32(0.f), f1 = f0, f2 = f0, f3 = f0;
                for (int g = 0; g < ng; g++) {
                    int32x4_t r[4];
                    int k = g * WH_GS;
                    const int8_t *hx[4] = {x0 + k, x1 + k, x2 + k, x3 + k};
                    const int8_t *lx[4] = {l0 + k, l1 + k, l2 + k, l3 + k};
                    pf_dot4x4_hilo(p0 + k, p1 + k, p2 + k, p3 + k, hx, lx, WH_GS, r);
                    float32x4_t sg = vld1q_f32(sc + g * 4);
                    f0 = vfmaq_f32(f0, vcvtq_f32_s32(r[0]), sg);
                    f1 = vfmaq_f32(f1, vcvtq_f32_s32(r[1]), sg);
                    f2 = vfmaq_f32(f2, vcvtq_f32_s32(r[2]), sg);
                    f3 = vfmaq_f32(f3, vcvtq_f32_s32(r[3]), sg);
                }
                int dcol = d0 + dr;
                pf_store4(out, D, s0, dcol + 0, f0);
                pf_store4(out, D, s0, dcol + 1, f1);
                pf_store4(out, D, s0, dcol + 2, f2);
                pf_store4(out, D, s0, dcol + 3, f3);
            }
        }
    }
}

#endif /* NEON dotprod */
#endif /* WH_PREFILL_GEMM_H */

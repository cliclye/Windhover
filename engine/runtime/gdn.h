/* gdn.h — Qwen3.5 Gated DeltaNet step (recurrent decode / sequential prefill).
 *
 * Matches transformers Qwen3_5GatedDeltaNet + torch_recurrent_gated_delta_rule
 * for text generation (vision tower stripped at pack time).
 */
#ifndef WH_GDN_H
#define WH_GDN_H

#include <math.h>
#include <string.h>

static inline float wh_silu_f(float x) {
    return x / (1.f + expf(-x));
}
static inline float wh_sigmoid_f(float x) {
    return 1.f / (1.f + expf(-x));
}
static inline float wh_softplus_f(float x) {
    /* Stable softplus */
    if (x > 20.f) return x;
    if (x < -20.f) return expf(x);
    return logf(1.f + expf(x));
}

/* y = W @ x  (float input; int8-row or f32 weights). */
static void wh_gemv_wt_f(const WT *w, const float *x, float *y, int O) {
    if (!w || w->fmt == WT_NONE || O <= 0) {
        if (O > 0) memset(y, 0, (size_t)O * sizeof(float));
        return;
    }
    if (O > w->O) O = w->O;
    int I = w->I;
    if (w->fmt == WT_I8R && w->q8 && w->rs) {
        for (int o = 0; o < O; o++) {
            const int8_t *row = w->q8 + (int64_t)o * I;
            float acc = 0.f;
            for (int j = 0; j < I; j++) acc += (float)row[j] * x[j];
            y[o] = acc * w->rs[o];
        }
    } else if (w->fmt == WT_F32 && w->f) {
        for (int o = 0; o < O; o++) {
            const float *row = w->f + (int64_t)o * I;
            float acc = 0.f;
            for (int j = 0; j < I; j++) acc += row[j] * x[j];
            y[o] = acc;
        }
    } else {
        memset(y, 0, (size_t)O * sizeof(float));
    }
}

/* Depthwise causal conv1d update for one token. weight: [C, K] row-major.
 * conv_state: [C * (K-1)] prior inputs (oldest first). mixed in/out: [C]. */
static void wh_causal_conv1d_update(float *mixed, float *conv_state,
                                    const float *weight, int C, int K,
                                    int do_silu) {
    if (K < 2 || !weight || !conv_state) {
        if (do_silu) for (int c = 0; c < C; c++) mixed[c] = wh_silu_f(mixed[c]);
        return;
    }
    int state_len = K - 1;
    for (int c = 0; c < C; c++) {
        float acc = 0.f;
        const float *wrow = weight + (int64_t)c * K;
        float *st = conv_state + (int64_t)c * state_len;
        for (int i = 0; i < state_len; i++) acc += st[i] * wrow[i];
        acc += mixed[c] * wrow[state_len];
        /* shift state ← …, new */
        for (int i = 0; i < state_len - 1; i++) st[i] = st[i + 1];
        if (state_len > 0) st[state_len - 1] = mixed[c];
        mixed[c] = do_silu ? wh_silu_f(acc) : acc;
    }
}

/* One-token Gated DeltaNet. Shapes from Qwen3.5 config:
 *   key_dim = nk*hk, value_dim = nv*hv, qkv_rows = 2*key_dim + value_dim
 * state: [nv][hk][hv]  (k-heads repeated to v-heads before the rule)
 */
static void wh_gdn_step(
    WLayer *l, const float *nrm, int D, float eps,
    float *state, float *conv_state,
    float *scratch_qkv, /* [qkv_rows] */
    float *scratch_z,   /* [value_dim] */
    float *scratch_ab,  /* [2 * nv] a then b, or just use two nv slots */
    float *out_d        /* [D] */
) {
    int nk = l->lin_nk > 0 ? l->lin_nk : 16;
    int nv = l->lin_nv > 0 ? l->lin_nv : 32;
    int hk = l->lin_hk > 0 ? l->lin_hk : 128;
    int hv = l->lin_hv > 0 ? l->lin_hv : 128;
    int key_dim = nk * hk;
    int value_dim = nv * hv;
    int qkv_rows = 2 * key_dim + value_dim;
    int Kconv = l->lin_conv_k > 0 ? l->lin_conv_k : 4;
    int ratio = nv / nk;
    if (ratio < 1) ratio = 1;

    /* Projections */
    wh_gemv_wt_f(&l->lin_qkv, nrm, scratch_qkv, qkv_rows);
    if (l->lin_conv_w) {
        wh_causal_conv1d_update(scratch_qkv, conv_state, l->lin_conv_w,
                                qkv_rows, Kconv, 1);
    }
    wh_gemv_wt_f(&l->lin_z, nrm, scratch_z, value_dim);
    float *a = scratch_ab;
    float *b = scratch_ab + nv;
    wh_gemv_wt_f(&l->lin_a, nrm, a, nv);
    wh_gemv_wt_f(&l->lin_b, nrm, b, nv);

    float *q = scratch_qkv;
    float *k = scratch_qkv + key_dim;
    float *v = scratch_qkv + 2 * key_dim;

    /* Expand k-heads → v-heads (repeat_interleave). Work in-place into
     * trailing value region temporarily via a small stack buffer per head. */
    /* We'll index q/k with head mapping: q_head = vh / ratio */

    float scale = 1.f / sqrtf((float)hk);
    for (int vh = 0; vh < nv; vh++) {
        int kh = vh / ratio;
        float *qh = q + kh * hk;
        float *khp = k + kh * hk;
        float *vhv = v + vh * hv;
        float *st = state + (int64_t)vh * hk * hv;

        /* L2-norm q,k for this (shared) k-head — compute once per kh when vh%ratio==0 */
        float qn[128], kn[128];
        if (hk > 128) {
            /* Should not happen for Qwen3.5 (hk=128); fall back without stack blow. */
            fprintf(stderr, "[wh] gdn hk=%d > 128\n", hk);
            return;
        }
        float qss = 0.f, kss = 0.f;
        for (int j = 0; j < hk; j++) {
            qss += qh[j] * qh[j];
            kss += khp[j] * khp[j];
        }
        float qsc = 1.f / sqrtf(qss + 1e-6f);
        float ksc = 1.f / sqrtf(kss + 1e-6f);
        for (int j = 0; j < hk; j++) {
            qn[j] = qh[j] * qsc * scale;
            kn[j] = khp[j] * ksc;
        }

        float beta = wh_sigmoid_f(b[vh]);
        float A = l->lin_A_log ? l->lin_A_log[vh] : 0.f;
        float dt = l->lin_dt_bias ? l->lin_dt_bias[vh] : 0.f;
        float g = -expf(A) * wh_softplus_f(a[vh] + dt);
        float decay = expf(g);

        /* state *= decay */
        for (int j = 0; j < hk * hv; j++) st[j] *= decay;

        /* kv_mem[v] = sum_k state[k,v] * key[k] */
        float mem[128];
        if (hv > 128) {
            fprintf(stderr, "[wh] gdn hv=%d > 128\n", hv);
            return;
        }
        memset(mem, 0, (size_t)hv * sizeof(float));
        for (int ki = 0; ki < hk; ki++) {
            float kk = kn[ki];
            const float *row = st + (int64_t)ki * hv;
            for (int vi = 0; vi < hv; vi++) mem[vi] += row[vi] * kk;
        }
        /* delta = (v - mem) * beta; state += k ⊗ delta; out = state^T q */
        float outh[128];
        memset(outh, 0, (size_t)hv * sizeof(float));
        for (int vi = 0; vi < hv; vi++) {
            float delta = (vhv[vi] - mem[vi]) * beta;
            for (int ki = 0; ki < hk; ki++) {
                st[(int64_t)ki * hv + vi] += kn[ki] * delta;
                outh[vi] += st[(int64_t)ki * hv + vi] * qn[ki];
            }
        }

        /* Gated RMSNorm over head_v_dim */
        float ms = 0.f;
        for (int vi = 0; vi < hv; vi++) ms += outh[vi] * outh[vi];
        float r = 1.f / sqrtf(ms / (float)hv + eps);
        float *zw = scratch_z + vh * hv;
        for (int vi = 0; vi < hv; vi++) {
            float w = l->lin_norm ? l->lin_norm[vi] : 1.f;
            outh[vi] = outh[vi] * r * w * wh_silu_f(zw[vi]);
        }
        /* Park head output back into v slot for out_proj packing */
        memcpy(vhv, outh, (size_t)hv * sizeof(float));
    }

    /* out_proj: value_dim → D */
    memset(out_d, 0, (size_t)D * sizeof(float));
    if (l->lin_out.fmt != WT_NONE) {
        wh_gemv_wt_f(&l->lin_out, v, out_d, D);
    }
}

/* ------------------------------------------------------------------------
 * Batched Gated DeltaNet layer over S tokens (prefill and decode).
 *
 * The per-token path above runs three scalar single-thread GEMVs per token
 * and walks the [hk][hv] state column-wise. Here:
 *   1. in_proj_qkv / in_proj_z run as one batched int8 GEMM over all S tokens
 *      (mm_wt_run: tiled + multi-threaded, reuses the quantized layer input),
 *   2. the depthwise causal conv is parallel over channels (each channel's
 *      history is independent), sequential over tokens,
 *   3. the delta-rule recurrence is parallel over value heads (each head owns
 *      its state), sequential over tokens, with the state updated row-wise:
 *        mem   = decay * S^T k
 *        S'    = decay * S + k (x) beta (v - mem)
 *        out   = S'^T q
 *      (two contiguous passes instead of four strided ones),
 *   4. out_proj is again one batched GEMM.
 * Output: out[S][D] (caller adds to the residual).
 * ------------------------------------------------------------------------ */
static void mm_wt_run(const WT *w, const int8_t *xq, const float *sx,
                      const int32_t *xqsum, float *y, int S, int ystride);
static float qrow(const float *x, int8_t *q, int32_t *gsum, int I);

static void wh_gdn_layer(WLayer *l, int S, int D, int I, float eps,
                         const float *nrm,            /* [S][D] normed input (f32) */
                         int8_t *xq, float *sx, int32_t *xqsum, /* [S][D] quantized input; reused */
                         float *state, float *conv_state,
                         float *qkv,                  /* [S][I] scratch (qkv rows <= I) */
                         float *zb,                   /* [S][I] scratch (value_dim <= I) */
                         float *ab,                   /* [S][2*nv] scratch */
                         float *out) {                /* [S][D] */
    int nk = l->lin_nk > 0 ? l->lin_nk : 16;
    int nv = l->lin_nv > 0 ? l->lin_nv : 32;
    int hk = l->lin_hk > 0 ? l->lin_hk : 128;
    int hv = l->lin_hv > 0 ? l->lin_hv : 128;
    int key_dim = nk * hk, value_dim = nv * hv;
    int qkv_rows = 2 * key_dim + value_dim;
    int Kc = l->lin_conv_k > 0 ? l->lin_conv_k : 4;
    int ratio = nv / nk; if (ratio < 1) ratio = 1;
    if (hk > 256 || hv > 256) {
        fprintf(stderr, "[wh] gdn head dims %d/%d unsupported\n", hk, hv);
        exit(1);
    }

    /* 1. projections (batched) */
    mm_wt_run(&l->lin_qkv, xq, sx, xqsum, qkv, S, I);
    mm_wt_run(&l->lin_z, xq, sx, xqsum, zb, S, I);
    #pragma omp parallel for schedule(static) if (S > 1)
    for (int s = 0; s < S; s++) {
        wh_gemv_wt_f(&l->lin_a, nrm + (int64_t)s * D, ab + (int64_t)s * 2 * nv, nv);
        wh_gemv_wt_f(&l->lin_b, nrm + (int64_t)s * D, ab + (int64_t)s * 2 * nv + nv, nv);
    }

    /* 2. causal depthwise conv + SiLU, parallel over channels */
    if (l->lin_conv_w && conv_state && Kc >= 2) {
        int sl = Kc - 1;
        #pragma omp parallel for schedule(static)
        for (int c = 0; c < qkv_rows; c++) {
            const float *wr = l->lin_conv_w + (int64_t)c * Kc;
            float *st = conv_state + (int64_t)c * sl;
            for (int s = 0; s < S; s++) {
                float *xp = qkv + (int64_t)s * I + c;
                float acc = *xp * wr[sl];
                for (int i = 0; i < sl; i++) acc += st[i] * wr[i];
                for (int i = 0; i < sl - 1; i++) st[i] = st[i + 1];
                st[sl - 1] = *xp;
                *xp = wh_silu_f(acc);
            }
        }
    } else {
        #pragma omp parallel for schedule(static)
        for (int c = 0; c < qkv_rows; c++)
            for (int s = 0; s < S; s++) {
                float *xp = qkv + (int64_t)s * I + c;
                *xp = wh_silu_f(*xp);
            }
    }

    /* 3. recurrence, parallel over value heads */
    float qscale = 1.f / sqrtf((float)hk);
    #pragma omp parallel for schedule(dynamic, 1)
    for (int vh = 0; vh < nv; vh++) {
        int kh = vh / ratio;
        float *st = state + (int64_t)vh * hk * hv;
        float A = l->lin_A_log ? l->lin_A_log[vh] : 0.f;
        float dtb = l->lin_dt_bias ? l->lin_dt_bias[vh] : 0.f;
        float negA = -expf(A);
        float qn[256], kn[256], mem[256], dl[256], oh[256];
        for (int s = 0; s < S; s++) {
            float *row = qkv + (int64_t)s * I;
            const float *qh = row + kh * hk;
            const float *kp = row + key_dim + kh * hk;
            float *vv = row + 2 * key_dim + vh * hv;
            float qss = 0.f, kss = 0.f;
            for (int j = 0; j < hk; j++) { qss += qh[j] * qh[j]; kss += kp[j] * kp[j]; }
            float qsc = qscale / sqrtf(qss + 1e-6f), ksc = 1.f / sqrtf(kss + 1e-6f);
            for (int j = 0; j < hk; j++) { qn[j] = qh[j] * qsc; kn[j] = kp[j] * ksc; }
            const float *abs_ = ab + (int64_t)s * 2 * nv;
            float beta = wh_sigmoid_f(abs_[nv + vh]);
            float decay = expf(negA * wh_softplus_f(abs_[vh] + dtb));
            /* mem = decay * S^T k */
            for (int vi = 0; vi < hv; vi++) mem[vi] = 0.f;
            for (int ki = 0; ki < hk; ki++) {
                float kk = kn[ki];
                const float *sr = st + (int64_t)ki * hv;
                for (int vi = 0; vi < hv; vi++) mem[vi] += sr[vi] * kk;
            }
            for (int vi = 0; vi < hv; vi++) {
                dl[vi] = (vv[vi] - decay * mem[vi]) * beta;
                oh[vi] = 0.f;
            }
            /* S' = decay*S + k (x) delta ; out = S'^T q */
            for (int ki = 0; ki < hk; ki++) {
                float kk = kn[ki], qq = qn[ki];
                float *sr = st + (int64_t)ki * hv;
                for (int vi = 0; vi < hv; vi++) {
                    float v = sr[vi] * decay + kk * dl[vi];
                    sr[vi] = v;
                    oh[vi] += v * qq;
                }
            }
            /* gated RMSNorm over head_v_dim, park into the v slot */
            float ms = 0.f;
            for (int vi = 0; vi < hv; vi++) ms += oh[vi] * oh[vi];
            float r = 1.f / sqrtf(ms / (float)hv + eps);
            const float *zw = zb + (int64_t)s * I + vh * hv;
            for (int vi = 0; vi < hv; vi++) {
                float w = l->lin_norm ? l->lin_norm[vi] : 1.f;
                vv[vi] = oh[vi] * r * w * wh_silu_f(zw[vi]);
            }
        }
    }

    /* 4. out_proj (batched): quantize each token's value block, one GEMM */
    if (l->lin_out.fmt == WT_NONE) {
        memset(out, 0, (size_t)S * D * sizeof(float));
        return;
    }
    if (l->lin_out.fmt == WT_F32) {
        for (int s = 0; s < S; s++)
            wh_gemv_wt_f(&l->lin_out, qkv + (int64_t)s * I + 2 * key_dim, out + (int64_t)s * D, D);
        return;
    }
    int ngv = value_dim / 64;
    for (int s = 0; s < S; s++)
        sx[s] = qrow(qkv + (int64_t)s * I + 2 * key_dim, xq + (int64_t)s * value_dim,
                     xqsum + (int64_t)s * ngv, value_dim);
    mm_wt_run(&l->lin_out, xq, sx, xqsum, out, S, D);
}

#endif /* WH_GDN_H */

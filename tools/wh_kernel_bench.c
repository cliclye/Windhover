/* wh_kernel_bench.c — Windhover Phase-0 gate microbenchmarks (standalone).
 *
 * NOT linked into the engine. Compiled ad hoc by tools/windhover_gates.py:
 *   clang -O3 -march=armv8.7-a+sme2 -Xclang -fopenmp -I$(brew --prefix libomp)/include \
 *         tools/wh_kernel_bench.c -o /tmp/wh_kernel_bench -L$(brew --prefix libomp)/lib -lomp -lm
 *
 * Subcommands (each prints ONE JSON object on stdout):
 *   stream            multithreaded streaming-read bandwidth ceiling
 *   g1                GEMV kernel ladder: int8-row / int4-row / int4-g64 / bundle layout
 *   g5                S=64 int8 GEMM: NEON SDOT vs i8mm SMMLA vs SME2 SMOPA
 *   g6 <file>         random-read throughput at AU bundle sizes (F_NOCACHE)
 *   g4 <file>         mmap residency: page-in rate, footprint, eviction under pressure
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/stat.h>
#if defined(__APPLE__)
#include <mach/mach.h>
#include <sys/sysctl.h>
#endif
#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif
#if defined(__ARM_FEATURE_SME2)
#include <arm_sme.h>
#endif
#ifdef _OPENMP
#include <omp.h>
#endif

static double now_s(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

static double phys_footprint_gb(void) {
#if defined(__APPLE__)
    task_vm_info_data_t vm;
    mach_msg_type_number_t cnt = TASK_VM_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&vm, &cnt) == KERN_SUCCESS)
        return (double)vm.phys_footprint / 1e9;
#endif
    return 0.0;
}

static void *xaligned(size_t n) {
    void *p = NULL;
    if (posix_memalign(&p, 16384, n) != 0 || !p) {
        fprintf(stderr, "OOM %zu bytes\n", n); exit(1);
    }
    return p;
}

static uint64_t rng_state = 0x9E3779B97F4A7C15ull;
static inline uint64_t rng_next(void) {
    rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17;
    return rng_state;
}
static float frand(void) { return ((int64_t)(rng_next() & 0xFFFFFF) - 0x800000) / (float)0x800000; }

/* ---------------- quantization helpers (mirror engine formats) ------------- */

/* per-row int4: absmax over whole row (dense.c pack_int4) */
static void pack_i4_row(const float *w, uint8_t *q4, float *scale, int O, int I) {
    int rb = (I + 1) / 2;
    for (int o = 0; o < O; o++) {
        const float *wr = w + (int64_t)o * I;
        float amax = 0.f;
        for (int i = 0; i < I; i++) { float a = fabsf(wr[i]); if (a > amax) amax = a; }
        float s = amax / 7.f; if (s < 1e-8f) s = 1e-8f;
        scale[o] = s;
        uint8_t *qr = q4 + (int64_t)o * rb;
        for (int i = 0; i < I; i += 2) {
            int v0 = (int)lrintf(wr[i] / s); if (v0 > 7) v0 = 7; if (v0 < -8) v0 = -8;
            int v1 = 0;
            if (i + 1 < I) { v1 = (int)lrintf(wr[i+1] / s); if (v1 > 7) v1 = 7; if (v1 < -8) v1 = -8; }
            qr[i >> 1] = (uint8_t)((v0 + 8) | ((v1 + 8) << 4));
        }
    }
}

/* group-64 int4: absmax per 64-elem group, fp16 scales [O][I/64] */
#define WH_GS 64
static void pack_i4_g64(const float *w, uint8_t *q4, __fp16 *scale, int O, int I) {
    int rb = (I + 1) / 2, ng = I / WH_GS;
    for (int o = 0; o < O; o++) {
        const float *wr = w + (int64_t)o * I;
        uint8_t *qr = q4 + (int64_t)o * rb;
        __fp16 *sr = scale + (int64_t)o * ng;
        for (int g = 0; g < ng; g++) {
            const float *wg = wr + g * WH_GS;
            float amax = 0.f;
            for (int i = 0; i < WH_GS; i++) { float a = fabsf(wg[i]); if (a > amax) amax = a; }
            float s = amax / 7.f; if (s < 1e-8f) s = 1e-8f;
            sr[g] = (__fp16)s;
            float inv = 1.f / s;
            for (int i = 0; i < WH_GS; i += 2) {
                int v0 = (int)lrintf(wg[i] * inv); if (v0 > 7) v0 = 7; if (v0 < -8) v0 = -8;
                int v1 = (int)lrintf(wg[i+1] * inv); if (v1 > 7) v1 = 7; if (v1 < -8) v1 = -8;
                qr[(g * WH_GS + i) >> 1] = (uint8_t)((v0 + 8) | ((v1 + 8) << 4));
            }
        }
    }
}

static void quant_i8_rows(const float *w, int8_t *q, float *scale, int O, int I) {
    for (int o = 0; o < O; o++) {
        const float *wr = w + (int64_t)o * I;
        float amax = 0.f;
        for (int i = 0; i < I; i++) { float a = fabsf(wr[i]); if (a > amax) amax = a; }
        float s = amax / 127.f; if (s < 1e-8f) s = 1e-8f;
        scale[o] = s;
        int8_t *qr = q + (int64_t)o * I;
        for (int i = 0; i < I; i++) {
            int v = (int)lrintf(wr[i] / s);
            if (v > 127) v = 127; if (v < -128) v = -128;
            qr[i] = (int8_t)v;
        }
    }
}

static float qrow_i8(const float *x, int8_t *q, int I) {
    float amax = 0.f;
    for (int i = 0; i < I; i++) { float a = fabsf(x[i]); if (a > amax) amax = a; }
    float s = amax / 127.f; if (s < 1e-12f) s = 1e-12f;
    float inv = 1.f / s;
    for (int i = 0; i < I; i++) q[i] = (int8_t)lrintf(x[i] * inv);
    return s;
}

/* ---------------- GEMV kernels ------------------------------------------- */

static inline int32_t dot_i8i8(const int8_t *w, const int8_t *x, int I) {
    int32_t sum = 0; int i = 0;
#if defined(__ARM_NEON) && defined(__ARM_FEATURE_DOTPROD)
    int32x4_t a0 = vdupq_n_s32(0), a1 = vdupq_n_s32(0), a2 = vdupq_n_s32(0), a3 = vdupq_n_s32(0);
    for (; i + 64 <= I; i += 64) {
        a0 = vdotq_s32(a0, vld1q_s8(w + i),      vld1q_s8(x + i));
        a1 = vdotq_s32(a1, vld1q_s8(w + i + 16), vld1q_s8(x + i + 16));
        a2 = vdotq_s32(a2, vld1q_s8(w + i + 32), vld1q_s8(x + i + 32));
        a3 = vdotq_s32(a3, vld1q_s8(w + i + 48), vld1q_s8(x + i + 48));
    }
    int32x4_t acc = vaddq_s32(vaddq_s32(a0, a1), vaddq_s32(a2, a3));
    for (; i + 16 <= I; i += 16) acc = vdotq_s32(acc, vld1q_s8(w + i), vld1q_s8(x + i));
    sum = vaddvq_s32(acc);
#endif
    for (; i < I; i++) sum += (int32_t)w[i] * x[i];
    return sum;
}

/* per-row int4 SDOT (current dense.c layout) */
static inline int32_t dot_i4i8_row(const uint8_t *w4, const int8_t *x, int I) {
    int32_t sum = 0; int i = 0;
#if defined(__ARM_NEON) && defined(__ARM_FEATURE_DOTPROD)
    const uint8x16_t m4q = vdupq_n_u8(0x0F);
    const int8x16_t b8q = vdupq_n_s8(8);
    int32x4_t a0 = vdupq_n_s32(0), a1 = vdupq_n_s32(0), a2 = vdupq_n_s32(0), a3 = vdupq_n_s32(0);
    for (; i + 64 <= I; i += 64) {
        uint8x16_t byA = vld1q_u8(w4 + (i >> 1)), byB = vld1q_u8(w4 + (i >> 1) + 16);
        uint8x16x2_t zA = vzipq_u8(vandq_u8(byA, m4q), vshrq_n_u8(byA, 4));
        uint8x16x2_t zB = vzipq_u8(vandq_u8(byB, m4q), vshrq_n_u8(byB, 4));
        a0 = vdotq_s32(a0, vsubq_s8(vreinterpretq_s8_u8(zA.val[0]), b8q), vld1q_s8(x + i));
        a1 = vdotq_s32(a1, vsubq_s8(vreinterpretq_s8_u8(zA.val[1]), b8q), vld1q_s8(x + i + 16));
        a2 = vdotq_s32(a2, vsubq_s8(vreinterpretq_s8_u8(zB.val[0]), b8q), vld1q_s8(x + i + 32));
        a3 = vdotq_s32(a3, vsubq_s8(vreinterpretq_s8_u8(zB.val[1]), b8q), vld1q_s8(x + i + 48));
    }
    int32x4_t acc = vaddq_s32(vaddq_s32(a0, a1), vaddq_s32(a2, a3));
    sum = vaddvq_s32(acc);
#endif
    for (; i + 1 < I; i += 2) {
        uint8_t b = w4[i >> 1];
        sum += ((int)(b & 0xF) - 8) * x[i] + ((int)(b >> 4) - 8) * x[i + 1];
    }
    return sum;
}

/* group-64 int4 SDOT GEMV row: per-group int32 dot folded by fp16 scale. */
static inline float dot_i4i8_g64(const uint8_t *w4, const __fp16 *sc, const int8_t *x, int I) {
    float acc = 0.f;
#if defined(__ARM_NEON) && defined(__ARM_FEATURE_DOTPROD)
    const uint8x16_t m4q = vdupq_n_u8(0x0F);
    const int8x16_t b8q = vdupq_n_s8(8);
    int ng = I / WH_GS;
    /* two groups per iteration -> two int32 partials -> fold via fp32 pair */
    int g = 0;
    float32x4_t facc = vdupq_n_f32(0.f);
    for (; g + 2 <= ng; g += 2) {
        const uint8_t *wg = w4 + (g * WH_GS >> 1);
        const int8_t *xg = x + g * WH_GS;
        uint8x16_t byA = vld1q_u8(wg),      byB = vld1q_u8(wg + 16);
        uint8x16_t byC = vld1q_u8(wg + 32), byD = vld1q_u8(wg + 48);
        uint8x16x2_t zA = vzipq_u8(vandq_u8(byA, m4q), vshrq_n_u8(byA, 4));
        uint8x16x2_t zB = vzipq_u8(vandq_u8(byB, m4q), vshrq_n_u8(byB, 4));
        uint8x16x2_t zC = vzipq_u8(vandq_u8(byC, m4q), vshrq_n_u8(byC, 4));
        uint8x16x2_t zD = vzipq_u8(vandq_u8(byD, m4q), vshrq_n_u8(byD, 4));
        int32x4_t p0 = vdupq_n_s32(0), p1 = vdupq_n_s32(0);
        p0 = vdotq_s32(p0, vsubq_s8(vreinterpretq_s8_u8(zA.val[0]), b8q), vld1q_s8(xg));
        p0 = vdotq_s32(p0, vsubq_s8(vreinterpretq_s8_u8(zA.val[1]), b8q), vld1q_s8(xg + 16));
        p0 = vdotq_s32(p0, vsubq_s8(vreinterpretq_s8_u8(zB.val[0]), b8q), vld1q_s8(xg + 32));
        p0 = vdotq_s32(p0, vsubq_s8(vreinterpretq_s8_u8(zB.val[1]), b8q), vld1q_s8(xg + 48));
        p1 = vdotq_s32(p1, vsubq_s8(vreinterpretq_s8_u8(zC.val[0]), b8q), vld1q_s8(xg + 64));
        p1 = vdotq_s32(p1, vsubq_s8(vreinterpretq_s8_u8(zC.val[1]), b8q), vld1q_s8(xg + 80));
        p1 = vdotq_s32(p1, vsubq_s8(vreinterpretq_s8_u8(zD.val[0]), b8q), vld1q_s8(xg + 96));
        p1 = vdotq_s32(p1, vsubq_s8(vreinterpretq_s8_u8(zD.val[1]), b8q), vld1q_s8(xg + 112));
        float s0 = (float)sc[g], s1 = (float)sc[g + 1];
        float32x2_t partials = { (float)vaddvq_s32(p0), (float)vaddvq_s32(p1) };
        float32x2_t scales = { s0, s1 };
        facc = vcombine_f32(vfma_f32(vget_low_f32(facc), partials, scales), vget_high_f32(facc));
    }
    acc = vaddvq_f32(facc);
    for (; g < ng; g++) {
        int32_t p = 0;
        const uint8_t *wg = w4 + (g * WH_GS >> 1);
        const int8_t *xg = x + g * WH_GS;
        for (int i = 0; i < WH_GS; i += 2) {
            uint8_t b = wg[i >> 1];
            p += ((int)(b & 0xF) - 8) * xg[i] + ((int)(b >> 4) - 8) * xg[i + 1];
        }
        acc += (float)p * (float)sc[g];
    }
#else
    (void)w4; (void)sc; (void)x; (void)I;
#endif
    return acc;
}

/* f64 reference */
static double dot_ref(const float *w, const float *x, int I) {
    double s = 0;
    for (int i = 0; i < I; i++) s += (double)w[i] * x[i];
    return s;
}

typedef struct { double gbs, ms; } BenchOut;

/* Effective weight-bandwidth of a GEMV kernel over `reps` runs. */
static BenchOut bench_gemv(int kind, const void *q, const void *sc, const int8_t *xq,
                           float sx, float *y, int O, int I, int reps) {
    int rb = (I + 1) / 2, ng = I / WH_GS;
    double bytes = 0;
    if (kind == 0) bytes = (double)O * I + O * 4.0;                 /* int8 + f32 row scale */
    else if (kind == 1) bytes = (double)O * rb + O * 4.0;           /* int4 row */
    else bytes = (double)O * rb + (double)O * ng * 2.0;             /* int4 g64 + fp16 scales */
    double best = 1e30;
    for (int r = 0; r < reps; r++) {
        double t0 = now_s();
        if (kind == 0) {
            const int8_t *w = (const int8_t *)q; const float *s = (const float *)sc;
            #pragma omp parallel for schedule(static)
            for (int o = 0; o < O; o++)
                y[o] = (float)dot_i8i8(w + (int64_t)o * I, xq, I) * s[o] * sx;
        } else if (kind == 1) {
            const uint8_t *w = (const uint8_t *)q; const float *s = (const float *)sc;
            #pragma omp parallel for schedule(static)
            for (int o = 0; o < O; o++)
                y[o] = (float)dot_i4i8_row(w + (int64_t)o * rb, xq, I) * s[o] * sx;
        } else {
            const uint8_t *w = (const uint8_t *)q; const __fp16 *s = (const __fp16 *)sc;
            #pragma omp parallel for schedule(static)
            for (int o = 0; o < O; o++)
                y[o] = dot_i4i8_g64(w + (int64_t)o * rb, s + (int64_t)o * ng, xq, I) * sx;
        }
        double dt = now_s() - t0;
        if (dt < best) best = dt;
    }
    BenchOut b = { bytes / best / 1e9, best * 1e3 };
    return b;
}

/* ---------------- subcommand: stream -------------------------------------- */

typedef struct { const uint8_t *p; size_t n; int reps; volatile uint64_t sink; } StreamArg;
static void *stream_worker(void *v) {
    StreamArg *a = (StreamArg *)v;
    const uint8_t *p = a->p; size_t n = a->n;
    uint64x2_t acc = vdupq_n_u64(0);
    for (int r = 0; r < a->reps; r++)
        for (size_t i = 0; i + 64 <= n; i += 64) {
            uint8x16_t v0 = vld1q_u8(p + i), v1 = vld1q_u8(p + i + 16);
            uint8x16_t v2 = vld1q_u8(p + i + 32), v3 = vld1q_u8(p + i + 48);
            acc = veorq_u64(acc, vreinterpretq_u64_u8(veorq_u8(veorq_u8(v0, v1), veorq_u8(v2, v3))));
        }
    a->sink = vgetq_lane_u64(acc, 0) ^ vgetq_lane_u64(acc, 1);
    return NULL;
}

/* pthread with max QoS so macOS schedules onto P-cores (default QoS lands on
 * E-cores and craters aggregate bandwidth). */
static void spawn_hi(pthread_t *th, void *(*fn)(void *), void *arg) {
    pthread_attr_t at;
    pthread_attr_init(&at);
#if defined(__APPLE__)
    pthread_attr_set_qos_class_np(&at, QOS_CLASS_USER_INTERACTIVE, 0);
#endif
    pthread_create(th, &at, fn, arg);
    pthread_attr_destroy(&at);
}

static int cmd_stream(void) {
    size_t per = 512ull << 20;
    int best_t = 0; double best_bw = 0;
    printf("{\"probe\":\"stream\",\"threads\":{");
    int cand[5] = { 1, 2, 4, 6, 8 };
    for (int ci = 0; ci < 5; ci++) {
        int nt = cand[ci];
        size_t n = per;
        uint8_t **bufs = malloc(sizeof(void *) * nt);
        for (int t = 0; t < nt; t++) { bufs[t] = xaligned(n); memset(bufs[t], 0xA5, n); }
        pthread_t th[16]; StreamArg args[16];
        int reps = 4;
        double best = 1e30;
        for (int trial = 0; trial < 2; trial++) {
            double t0 = now_s();
            for (int t = 0; t < nt; t++) { args[t].p = bufs[t]; args[t].n = n; args[t].reps = reps; spawn_hi(&th[t], stream_worker, &args[t]); }
            for (int t = 0; t < nt; t++) pthread_join(th[t], NULL);
            double dt = now_s() - t0;
            if (dt < best) best = dt;
        }
        double bw = (double)n * reps * nt / best / 1e9;
        printf("%s\"%d\":%.1f", ci == 0 ? "" : ",", nt, bw);
        if (bw > best_bw) { best_bw = bw; best_t = nt; }
        for (int t = 0; t < nt; t++) free(bufs[t]);
        free(bufs);
    }
    printf("},\"best_gbs\":%.1f,\"best_threads\":%d}\n", best_bw, best_t);
    return 0;
}

/* ---------------- subcommand: g1 ------------------------------------------ */

static void g1_shape(const char *name, int O, int I, int nthreads, int first) {
    float *W = xaligned((size_t)O * I * 4);
    for (int64_t i = 0; i < (int64_t)O * I; i++) W[i] = frand() * 0.04f;
    /* inject a few outliers per row like real LLM weights */
    for (int o = 0; o < O; o++) W[(int64_t)o * I + (rng_next() % I)] = frand() * 0.5f;

    float *x = xaligned(I * 4);
    for (int i = 0; i < I; i++) x[i] = frand();
    int8_t *xq = xaligned(I);
    float sx = qrow_i8(x, xq, I);

    int rb = (I + 1) / 2, ng = I / WH_GS;
    int8_t *q8 = xaligned((size_t)O * I); float *s8 = xaligned(O * 4);
    uint8_t *q4r = xaligned((size_t)O * rb); float *s4r = xaligned(O * 4);
    uint8_t *q4g = xaligned((size_t)O * rb); __fp16 *s4g = xaligned((size_t)O * ng * 2);
    quant_i8_rows(W, q8, s8, O, I);
    pack_i4_row(W, q4r, s4r, O, I);
    pack_i4_g64(W, q4g, s4g, O, I);

    float *y = xaligned(O * 4);
    int reps = O > 100000 ? 6 : 12;

    BenchOut b8 = bench_gemv(0, q8, s8, xq, sx, y, O, I, reps);
    BenchOut b4r = bench_gemv(1, q4r, s4r, xq, sx, y, O, I, reps);
    BenchOut b4g = bench_gemv(2, q4g, s4g, xq, sx, y, O, I, reps);

    /* numeric error vs f64 reference on 128 sample rows (dequant-int path) */
    double err_row = 0, err_g64 = 0, ref_mag = 0;
    for (int t = 0; t < 128; t++) {
        int o = (int)(rng_next() % O);
        double ref = dot_ref(W + (int64_t)o * I, x, I);
        float yr = (float)dot_i4i8_row(q4r + (int64_t)o * rb, xq, I) * s4r[o] * sx;
        float yg = dot_i4i8_g64(q4g + (int64_t)o * rb, s4g + (int64_t)o * ng, xq, I) * sx;
        err_row += (yr - ref) * (yr - ref);
        err_g64 += (yg - ref) * (yg - ref);
        ref_mag += ref * ref;
    }
    double rel_row = sqrt(err_row / (ref_mag + 1e-30));
    double rel_g64 = sqrt(err_g64 / (ref_mag + 1e-30));

    printf("%s\"%s\":{\"O\":%d,\"I\":%d,\"threads\":%d,"
           "\"int8_row\":{\"gbs\":%.1f,\"ms\":%.3f},"
           "\"int4_row\":{\"gbs\":%.1f,\"ms\":%.3f,\"rel_err\":%.2e},"
           "\"int4_g64\":{\"gbs\":%.1f,\"ms\":%.3f,\"rel_err\":%.2e}}",
           first ? "" : ",", name, O, I, nthreads,
           b8.gbs, b8.ms, b4r.gbs, b4r.ms, rel_row, b4g.gbs, b4g.ms, rel_g64);
    fflush(stdout);
    free(W); free(x); free(xq); free(q8); free(s8); free(q4r); free(s4r); free(q4g); free(s4g); free(y);
}

static int cmd_g1(void) {
    int nt = 1;
#ifdef _OPENMP
    nt = omp_get_max_threads();
#endif
    printf("{\"probe\":\"g1\",\"shapes\":{");
    /* Qwen2.5-1.5B: hidden 1536, inter 8960; Qwen2.5-7B: hidden 3584, inter 18944 */
    g1_shape("gate_1.5b", 8960, 1536, nt, 1);
    g1_shape("down_1.5b", 1536, 8960, nt, 0);
    g1_shape("lm_1.5b", 151936, 1536, nt, 0);
    g1_shape("gate_7b", 18944, 3584, nt, 0);
    g1_shape("down_7b", 3584, 18944, nt, 0);
    printf("}}\n");
    return 0;
}

/* ---------------- subcommand: g5 (S=64 GEMM) ------------------------------ */

/* NEON SDOT GEMM: per-token GEMV loop (engine's current prefill behavior). */
static double gemm_sdot_pertoken(const int8_t *W, const float *ws, const int8_t *X,
                                 const float *xs, float *C, int O, int I, int S, int reps) {
    double best = 1e30;
    for (int r = 0; r < reps; r++) {
        double t0 = now_s();
        for (int s = 0; s < S; s++) {
            const int8_t *x = X + (int64_t)s * I;
            #pragma omp parallel for schedule(static)
            for (int o = 0; o < O; o++)
                C[(int64_t)s * O + o] = (float)dot_i8i8(W + (int64_t)o * I, x, I) * ws[o] * xs[s];
        }
        double dt = now_s() - t0;
        if (dt < best) best = dt;
    }
    return best;
}

#if defined(__ARM_NEON) && defined(__ARM_FEATURE_MATMUL_INT8)
/* i8mm SMMLA GEMM: 2x2 output tiles, X packed [s2][k8] pairs. */
static double gemm_i8mm(const int8_t *W, const float *ws, const int8_t *Xp,
                        const float *xs, float *C, int O, int I, int S, int reps) {
    double best = 1e30;
    for (int r = 0; r < reps; r++) {
        double t0 = now_s();
        #pragma omp parallel for schedule(static)
        for (int o = 0; o < O; o += 2) {
            const int8_t *w0 = W + (int64_t)o * I;
            const int8_t *w1 = W + (int64_t)(o + 1) * I;
            for (int s = 0; s < S; s += 2) {
                const int8_t *xp = Xp + (int64_t)s * I; /* two tokens interleaved [k8 t0][k8 t1] */
                int32x4_t acc = vdupq_n_s32(0);
                for (int k = 0; k + 16 <= I; k += 16) {
                    int8x16_t a0 = vcombine_s8(vld1_s8(w0 + k), vld1_s8(w1 + k));
                    int8x16_t a1 = vcombine_s8(vld1_s8(w0 + k + 8), vld1_s8(w1 + k + 8));
                    int8x16_t b0 = vld1q_s8(xp + 2 * k);
                    int8x16_t b1 = vld1q_s8(xp + 2 * k + 16);
                    acc = vmmlaq_s32(acc, a0, b0);
                    acc = vmmlaq_s32(acc, a1, b1);
                }
                /* acc = [w0.t0, w0.t1, w1.t0, w1.t1] */
                C[(int64_t)s * O + o]       = (float)vgetq_lane_s32(acc, 0) * ws[o] * xs[s];
                C[(int64_t)(s+1) * O + o]   = (float)vgetq_lane_s32(acc, 1) * ws[o] * xs[s+1];
                C[(int64_t)s * O + o + 1]     = (float)vgetq_lane_s32(acc, 2) * ws[o+1] * xs[s];
                C[(int64_t)(s+1) * O + o + 1] = (float)vgetq_lane_s32(acc, 3) * ws[o+1] * xs[s+1];
            }
        }
        double dt = now_s() - t0;
        if (dt < best) best = dt;
    }
    return best;
}
#endif

#if defined(__ARM_FEATURE_SME2)
/* SME2 SMOPA GEMM. W panel-packed: 16 rows, k in groups of 4 -> Wp[k/4][row16][4].
 * X packed: Xp[k/4][col16][4]. ZA0..3 accumulate 16x16 int32 tiles across 64 cols. */
__arm_locally_streaming __arm_new("za")
static void sme_gemm_panel(const int8_t *Wp, const int8_t *Xp, int32_t *Ct, int I, int ncols) {
    /* one 16-row panel x ncols (multiple of 16, max 64) */
    svbool_t pg = svptrue_b8();
    int ntile = ncols / 16;
    svzero_za();
    for (int k4 = 0; k4 < I / 4; k4++) {
        svint8_t wv = svld1_s8(pg, Wp + (int64_t)k4 * 64);
        for (int t = 0; t < ntile; t++) {
            svint8_t xv = svld1_s8(pg, Xp + ((int64_t)k4 * ntile + t) * 64);
            switch (t) {
            case 0: svmopa_za32_s8_m(0, svptrue_b8(), svptrue_b8(), wv, xv); break;
            case 1: svmopa_za32_s8_m(1, svptrue_b8(), svptrue_b8(), wv, xv); break;
            case 2: svmopa_za32_s8_m(2, svptrue_b8(), svptrue_b8(), wv, xv); break;
            case 3: svmopa_za32_s8_m(3, svptrue_b8(), svptrue_b8(), wv, xv); break;
            }
        }
    }
    /* store tiles: rows of ZA0..3 -> Ct[row][tile*16 + col] */
    svbool_t pw = svptrue_b32();
    for (int row = 0; row < 16; row++) {
        for (int t = 0; t < ntile; t++) {
            svint32_t v;
            switch (t) {
            case 0: v = svread_hor_za32_s32_m(svdup_s32(0), pw, 0, row); break;
            case 1: v = svread_hor_za32_s32_m(svdup_s32(0), pw, 1, row); break;
            case 2: v = svread_hor_za32_s32_m(svdup_s32(0), pw, 2, row); break;
            default: v = svread_hor_za32_s32_m(svdup_s32(0), pw, 3, row); break;
            }
            svst1_s32(pw, Ct + ((int64_t)row * ncols) + t * 16, v);
        }
    }
}

static double gemm_sme(const int8_t *Wp, const float *ws, const int8_t *Xp, const float *xs,
                       float *C, int O, int I, int S, int reps) {
    int32_t *Ct = xaligned((size_t)16 * S * 4);
    double best = 1e30;
    for (int r = 0; r < reps; r++) {
        double t0 = now_s();
        for (int op = 0; op < O; op += 16) {
            sme_gemm_panel(Wp + (int64_t)op * I, Xp, Ct, I, S);
            for (int row = 0; row < 16; row++)
                for (int s = 0; s < S; s++)
                    C[(int64_t)s * O + op + row] = (float)Ct[row * S + s] * ws[op + row] * xs[s];
        }
        double dt = now_s() - t0;
        if (dt < best) best = dt;
    }
    free(Ct);
    return best;
}
#endif

static int cmd_g5(void) {
    const int O = 8960, I = 1536, S = 64;
    int8_t *W = xaligned((size_t)O * I);
    for (int64_t i = 0; i < (int64_t)O * I; i++) W[i] = (int8_t)(rng_next() % 15) - 7;
    float *ws = xaligned(O * 4);
    for (int o = 0; o < O; o++) ws[o] = 0.01f;
    int8_t *X = xaligned((size_t)S * I);
    for (int64_t i = 0; i < (int64_t)S * I; i++) X[i] = (int8_t)(rng_next() % 15) - 7;
    float *xs = xaligned(S * 4);
    for (int s = 0; s < S; s++) xs[s] = 0.02f;
    float *C = xaligned((size_t)S * O * 4);
    double ops = 2.0 * O * I * S;
    int reps = 8;

    double t_sdot = gemm_sdot_pertoken(W, ws, X, xs, C, O, I, S, reps);
    double c_ref = C[123];

    double t_i8mm = -1; double c_i8mm = 0;
#if defined(__ARM_NEON) && defined(__ARM_FEATURE_MATMUL_INT8)
    /* pack X pairs: [s2][k8 t0][k8 t1] */
    int8_t *Xp = xaligned((size_t)S * I);
    for (int s = 0; s < S; s += 2)
        for (int k = 0; k < I; k += 8)
            for (int b = 0; b < 8; b++) {
                Xp[(int64_t)s * I + 2 * k + b]     = X[(int64_t)s * I + k + b];
                Xp[(int64_t)s * I + 2 * k + 8 + b] = X[(int64_t)(s + 1) * I + k + b];
            }
    t_i8mm = gemm_i8mm(W, ws, Xp, xs, C, O, I, S, reps);
    c_i8mm = C[123];
    free(Xp);
#endif

    double t_sme = -1; double c_sme = 0;
#if defined(__ARM_FEATURE_SME2)
    /* panel-pack W: [opanel][k/4][row16][4]; pack X: [k/4][tile][col16][4] */
    int8_t *Wp = xaligned((size_t)O * I);
    for (int op = 0; op < O; op += 16)
        for (int k4 = 0; k4 < I / 4; k4++)
            for (int row = 0; row < 16; row++)
                for (int b = 0; b < 4; b++)
                    Wp[(int64_t)op * I + (int64_t)k4 * 64 + row * 4 + b] = W[(int64_t)(op + row) * I + k4 * 4 + b];
    int ntile = S / 16;
    int8_t *Xs = xaligned((size_t)S * I);
    for (int k4 = 0; k4 < I / 4; k4++)
        for (int t = 0; t < ntile; t++)
            for (int col = 0; col < 16; col++)
                for (int b = 0; b < 4; b++)
                    Xs[((int64_t)k4 * ntile + t) * 64 + col * 4 + b] = X[(int64_t)(t * 16 + col) * I + k4 * 4 + b];
    t_sme = gemm_sme(Wp, ws, Xs, xs, C, O, I, S, reps);
    c_sme = C[123];
    free(Wp); free(Xs);
#endif

    printf("{\"probe\":\"g5\",\"O\":%d,\"I\":%d,\"S\":%d,"
           "\"sdot_pertoken\":{\"ms\":%.2f,\"gops\":%.0f},"
           "\"i8mm\":{\"ms\":%.2f,\"gops\":%.0f,\"match\":%d},"
           "\"sme2\":{\"ms\":%.2f,\"gops\":%.0f,\"match\":%d}}\n",
           O, I, S,
           t_sdot * 1e3, ops / t_sdot / 1e9,
           t_i8mm * 1e3, t_i8mm > 0 ? ops / t_i8mm / 1e9 : 0, fabs(c_i8mm - c_ref) < 1e-3,
           t_sme * 1e3, t_sme > 0 ? ops / t_sme / 1e9 : 0, fabs(c_sme - c_ref) < 1e-3);
    free(W); free(ws); free(X); free(xs); free(C);
    return 0;
}

/* ---------------- subcommand: g6 (SSD random read) ------------------------ */

typedef struct { int fd; size_t fsize; int bs; int nreads; volatile uint64_t sink; } G6Arg;
static void *g6_worker(void *v) {
    G6Arg *a = (G6Arg *)v;
    uint8_t *buf = xaligned(a->bs);
    uint64_t acc = 0;
    for (int i = 0; i < a->nreads; i++) {
        off_t off = (off_t)((rng_next() % (a->fsize - a->bs)) & ~((uint64_t)16383));
        ssize_t rd = pread(a->fd, buf, a->bs, off);
        if (rd > 0) acc ^= buf[0];
    }
    a->sink = acc;
    free(buf);
    return NULL;
}

static int cmd_g6(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); return 1; }
#if defined(__APPLE__)
    fcntl(fd, F_NOCACHE, 1);
#endif
    struct stat st_;
    fstat(fd, &st_);
    size_t fsize = st_.st_size;
    printf("{\"probe\":\"g6\",\"file_gb\":%.2f,\"runs\":{", fsize / 1e9);
    int first = 1;
    int sizes[3] = { 24576, 32768, 65536 };
    for (int si = 0; si < 3; si++) {
        for (int nt = 1; nt <= 8; nt *= 2) {
            int bs = sizes[si];
            int nreads = (int)(512ll << 20) / bs / nt; /* 512MB total */
            pthread_t th[8]; G6Arg args[8];
            double t0 = now_s();
            for (int t = 0; t < nt; t++) {
                args[t].fd = fd; args[t].fsize = fsize; args[t].bs = bs; args[t].nreads = nreads;
                pthread_create(&th[t], NULL, g6_worker, &args[t]);
            }
            for (int t = 0; t < nt; t++) pthread_join(th[t], NULL);
            double dt = now_s() - t0;
            double gbs = (double)bs * nreads * nt / dt / 1e9;
            printf("%s\"%dKBx%d\":%.2f", first ? "" : ",", bs / 1024, nt, gbs);
            first = 0;
            fflush(stdout);
        }
    }
    printf("}}\n");
    close(fd);
    return 0;
}

/* ---------------- subcommand: g4 (mmap residency) -------------------------- */

static int cmd_g4(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); return 1; }
    struct stat st_;
    fstat(fd, &st_);
    size_t n = st_.st_size;
    double fp0 = phys_footprint_gb();
    uint8_t *p = mmap(NULL, n, PROT_READ, MAP_PRIVATE, fd, 0);
    if (p == MAP_FAILED) { perror("mmap"); return 1; }
    double fp_mapped = phys_footprint_gb();

    /* sequential touch = cold page-in rate */
    double t0 = now_s();
    volatile uint64_t acc = 0;
    for (size_t i = 0; i < n; i += 16384) acc ^= p[i];
    double t_cold = now_s() - t0;
    double fp_touched = phys_footprint_gb();

    /* warm re-touch */
    t0 = now_s();
    for (size_t i = 0; i < n; i += 16384) acc ^= p[i];
    double t_warm = now_s() - t0;

    /* memory pressure: dirty ~70% of free RAM, then re-touch file pages */
    int64_t memsize = 0;
    size_t len = sizeof(memsize);
    sysctlbyname("hw.memsize", &memsize, &len, NULL, 0);
    size_t pressure = (size_t)(memsize * 0.55);
    uint8_t *dirt = malloc(pressure);
    for (size_t i = 0; i < pressure; i += 16384) dirt[i] = (uint8_t)i;
    double fp_pressure = phys_footprint_gb();

    t0 = now_s();
    for (size_t i = 0; i < n; i += 16384) acc ^= p[i];
    double t_after_pressure = now_s() - t0;
    double fp_end = phys_footprint_gb();
    free(dirt);
    (void)acc;

    printf("{\"probe\":\"g4\",\"file_gb\":%.2f,"
           "\"footprint_gb\":{\"start\":%.2f,\"mapped\":%.2f,\"touched\":%.2f,\"under_pressure\":%.2f,\"end\":%.2f},"
           "\"cold_pagein_gbs\":%.2f,\"warm_touch_gbs\":%.2f,\"retouch_after_pressure_gbs\":%.2f}\n",
           n / 1e9, fp0, fp_mapped, fp_touched, fp_pressure, fp_end,
           n / t_cold / 1e9, n / t_warm / 1e9, n / t_after_pressure / 1e9);
    munmap(p, n);
    close(fd);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s stream|g1|g5|g6 <file>|g4 <file>\n", argv[0]);
        return 2;
    }
    if (!strcmp(argv[1], "stream")) return cmd_stream();
    if (!strcmp(argv[1], "g1")) return cmd_g1();
    if (!strcmp(argv[1], "g5")) return cmd_g5();
    if (!strcmp(argv[1], "g6") && argc > 2) return cmd_g6(argv[2]);
    if (!strcmp(argv[1], "g4") && argc > 2) return cmd_g4(argv[2]);
    fprintf(stderr, "unknown subcommand\n");
    return 2;
}

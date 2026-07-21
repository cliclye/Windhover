/* model_desc.h — Windhover architecture descriptor.
 *
 * Replaces string-sniffing (dense_is_arch) with a small table of layer
 * contracts. A pack is served by the Windhover runtime when either:
 *   - kestrel.json carries a "windhover" block (KPK pack, preferred), or
 *   - config.json model_type is in the supported table (raw HF pack:
 *     loader falls back to load-time quantization).
 *
 * Supported dense families: qwen2, qwen3, llama, mistral, gemma2, gemma3,
 * phi3. MoE configs are always routed to the engine.c MoE path.
 */
#ifndef WH_MODEL_DESC_H
#define WH_MODEL_DESC_H

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "json.h"

typedef enum { WH_ACT_SILU = 0, WH_ACT_GELU_TANH = 1 } WhAct;
typedef enum { WH_NORM_RMS = 0, WH_NORM_RMS_GEMMA = 1 } WhNorm; /* gemma: (1+w) */

typedef struct {
    char model_type[32];
    int hidden, layers, heads, kv_heads, head_dim, inter, vocab;
    float rope_theta, eps;
    int eos_id, bos_id;
    int tie_embeddings;
    WhAct act;
    WhNorm norm;
    int qkv_bias;          /* qwen2 */
    int qk_norm;           /* qwen3 / gemma3: per-head RMSNorm on q,k */
    int post_norms;        /* gemma: post_attention/pre+post_feedforward sandwich */
    int sliding_window;    /* 0 = none; gemma2/3, mistral */
    int sw_pattern;        /* every Nth layer is global (gemma2:2, gemma3:6); 0=all SW */
    float attn_softcap;    /* gemma2 attention logit softcapping */
    float final_softcap;   /* gemma2 final logit softcapping */
    float embed_scale;     /* gemma: sqrt(hidden) multiplier on embeddings */
    float query_scale;     /* attention 1/sqrt(query_pre_attn_scalar or head_dim) */
    int fused_qkv;         /* phi3 on-disk layout (split by converter) */
    int fused_gate_up;     /* phi3 */
    int max_position;      /* clamp CTX (phi3 longrope not implemented) */
} WhDesc;

static const char *WH_DENSE_TYPES[] = {
    "qwen2", "qwen3", "llama", "mistral", "gemma2", "gemma3", "phi3", NULL
};

static const char *WH_MOE_MARKERS[] = {
    "glm_moe_dsa", "n_routed_experts", "\"num_experts\"", "num_local_experts",
    "MixtralForCausalLM", "Qwen2MoeForCausalLM", "Qwen3MoeForCausalLM", NULL
};

static char *wh_read_file_(const char *path, long *out_n) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1);
    if (!b) { fclose(f); return NULL; }
    if (fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); fclose(f); return NULL; }
    b[n] = 0;
    fclose(f);
    if (out_n) *out_n = n;
    return b;
}

static int wh_ji_(jval *r, const char *k, int def) {
    jval *v = json_get(r, k);
    if (!v) return def;
    if (v->t == J_ARR && v->len > 0) v = v->kids[0]; /* eos_token_id: [a,b] */
    return (int)v->num;
}
static float wh_jf_(jval *r, const char *k, float def) {
    jval *v = json_get(r, k);
    return v ? (float)v->num : def;
}

/* 0 = not a supported dense arch (or is MoE), 1 = ok. */
static int wh_desc_from_config(const char *snap, WhDesc *d) {
    char path[2048];
    snprintf(path, sizeof(path), "%s/config.json", snap);
    long n = 0;
    char *buf = wh_read_file_(path, &n);
    if (!buf) return 0;
    for (int i = 0; WH_MOE_MARKERS[i]; i++)
        if (strstr(buf, WH_MOE_MARKERS[i])) { free(buf); return 0; }

    char *arena = NULL;
    jval *r = json_parse(buf, &arena);
    if (!r) { free(buf); return 0; }
    jval *mt = json_get(r, "model_type");
    if (!mt || mt->t != J_STR) { free(buf); free(arena); return 0; }

    int ok = 0;
    for (int i = 0; WH_DENSE_TYPES[i]; i++)
        if (!strcmp(mt->str, WH_DENSE_TYPES[i])) { ok = 1; break; }
    if (!ok) { free(buf); free(arena); return 0; }

    memset(d, 0, sizeof(*d));
    snprintf(d->model_type, sizeof(d->model_type), "%s", mt->str);
    d->hidden = wh_ji_(r, "hidden_size", 0);
    d->layers = wh_ji_(r, "num_hidden_layers", 0);
    d->heads = wh_ji_(r, "num_attention_heads", 0);
    d->kv_heads = wh_ji_(r, "num_key_value_heads", d->heads);
    d->inter = wh_ji_(r, "intermediate_size", 0);
    d->vocab = wh_ji_(r, "vocab_size", 0);
    d->head_dim = wh_ji_(r, "head_dim", d->heads ? d->hidden / d->heads : 0);
    if (d->head_dim <= 0 && d->heads > 0) d->head_dim = d->hidden / d->heads;
    d->rope_theta = wh_jf_(r, "rope_theta", 10000.f);
    d->eps = wh_jf_(r, "rms_norm_eps", 1e-6f);
    d->eos_id = wh_ji_(r, "eos_token_id", -1);
    d->bos_id = wh_ji_(r, "bos_token_id", -1);
    jval *tie = json_get(r, "tie_word_embeddings");
    d->tie_embeddings = (tie && tie->t == J_BOOL) ? tie->boolean : 0;
    d->max_position = wh_ji_(r, "max_position_embeddings", 0);
    d->act = WH_ACT_SILU;
    d->norm = WH_NORM_RMS;
    d->query_scale = 0.f; /* 0 -> 1/sqrt(head_dim) */

    if (!strcmp(d->model_type, "qwen2")) {
        d->qkv_bias = 1;
    } else if (!strcmp(d->model_type, "qwen3")) {
        d->qk_norm = 1;
    } else if (!strcmp(d->model_type, "mistral")) {
        d->sliding_window = wh_ji_(r, "sliding_window", 0);
    } else if (!strcmp(d->model_type, "gemma2")) {
        d->act = WH_ACT_GELU_TANH;
        d->norm = WH_NORM_RMS_GEMMA;
        d->post_norms = 1;
        d->sliding_window = wh_ji_(r, "sliding_window", 4096);
        d->sw_pattern = 2;
        d->attn_softcap = wh_jf_(r, "attn_logit_softcapping", 50.f);
        d->final_softcap = wh_jf_(r, "final_logit_softcapping", 30.f);
        d->embed_scale = sqrtf((float)d->hidden);
        float qs = wh_jf_(r, "query_pre_attn_scalar", 0.f);
        if (qs > 0) d->query_scale = 1.f / sqrtf(qs);
    } else if (!strcmp(d->model_type, "gemma3")) {
        d->act = WH_ACT_GELU_TANH;
        d->norm = WH_NORM_RMS_GEMMA;
        d->post_norms = 1;
        d->qk_norm = 1;
        d->sliding_window = wh_ji_(r, "sliding_window", 1024);
        d->sw_pattern = wh_ji_(r, "sliding_window_pattern", 6);
        d->embed_scale = sqrtf((float)d->hidden);
    } else if (!strcmp(d->model_type, "phi3")) {
        d->fused_qkv = 1;
        d->fused_gate_up = 1;
    }
    free(buf);
    free(arena);
    return d->hidden > 0 && d->layers > 0 && d->heads > 0 &&
           d->inter > 0 && d->vocab > 0;
}

/* 1 se la dir e' un pack KPK (kestrel.json con blocco windhover). */
static int wh_is_kpk(const char *snap) {
    char path[2048];
    snprintf(path, sizeof(path), "%s/kestrel.json", snap);
    long n = 0;
    char *buf = wh_read_file_(path, &n);
    if (!buf) return 0;
    int hit = strstr(buf, "\"windhover\"") != NULL;
    free(buf);
    return hit;
}

#endif

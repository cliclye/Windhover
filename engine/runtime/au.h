/* au.h — Windhover activation-unit (AU) tier manager.
 *
 * An AU is the atomic residency unit of sparse execution:
 *   - dense models: a bundle of AU_BUNDLE consecutive FFN neurons
 *     (gate row + up row + down^T row triples, hotness-permuted at convert)
 *   - MoE models: one routed expert (adapter: engine.c reports its existing
 *     expert cache into the shared ledger/telemetry; eviction stays there)
 *
 * The pool tracks, per (layer, bundle): tier (HOT = mlocked prefix under the
 * byte budget, COLD = mmap tail) and an activation EMA. The decode path asks
 * `au_filter` which gated-in neurons to keep: HOT bundles are free; COLD
 * bundles are fetched (counted) only when the gate magnitude clears the
 * cold threshold, otherwise dropped (counted). With the whole model under
 * budget every bundle is HOT and execution is exact CATS-only.
 */
#ifndef WH_AU_H
#define WH_AU_H

#include <stdint.h>

#define AU_BUNDLE 64

typedef struct {
    int layers, units;          /* units = ceil(inter / AU_BUNDLE) per layer */
    int64_t unit_bytes;         /* weight bytes touched per bundle (3 tensors) */
    int hot_units;              /* per-layer HOT prefix length (post-permute) */
    float *ema;                 /* [layers*units] activation EMA */
    /* telemetry (per run) */
    int64_t hot_hits, cold_fetches, cold_drops;
    int64_t bytes_saved;        /* skipped rows * row bytes */
    int enabled;                /* 0 -> all HOT (model fits budget) */
} AuPool;

/* Plan the HOT prefix from a byte budget. `resident_other` = bytes that must
 * stay resident regardless (attn + gate + embed + lm + kv + scratch). */
void au_plan(AuPool *p, int layers, int inter, int64_t unit_bytes,
             int64_t budget_bytes, int64_t resident_other);

/* Filter a gated-in neuron list for one layer (decode path).
 * keep[i]=1 for neurons to compute. gmag = |act(gate_j)| for each candidate.
 * Returns number kept. Updates telemetry + EMA. */
int au_filter(AuPool *p, int layer, const int *J, const float *gmag, int nJ,
              float tau_cold, unsigned char *keep);

void au_note_bytes_saved(AuPool *p, int64_t bytes);
void au_stats_line(AuPool *p, char *buf, int n);
void au_free(AuPool *p);

/* ---- shared ledger (dense pool + MoE adapter report into one place) ---- */
void au_ledger_set_budget(int64_t bytes);
void au_ledger_report(const char *klass, int64_t bytes_resident,
                      int64_t hits, int64_t misses);
void au_ledger_line(char *buf, int n);

#endif

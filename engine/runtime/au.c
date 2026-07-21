/* au.c — Windhover activation-unit tier manager (see au.h). */
#include "au.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void au_plan(AuPool *p, int layers, int inter, int64_t unit_bytes,
             int64_t budget_bytes, int64_t resident_other) {
    memset(p, 0, sizeof(*p));
    p->layers = layers;
    p->units = (inter + AU_BUNDLE - 1) / AU_BUNDLE;
    p->unit_bytes = unit_bytes;
    int64_t ffn_total = (int64_t)layers * p->units * unit_bytes;
    int64_t avail = budget_bytes - resident_other;
    if (budget_bytes <= 0 || avail >= ffn_total) {
        /* everything fits: exact mode, no cold tier */
        p->hot_units = p->units;
        p->enabled = 0;
        return;
    }
    if (avail < 0) avail = 0;
    int64_t per_layer = avail / layers;
    p->hot_units = (int)(per_layer / unit_bytes);
    if (p->hot_units < 1) p->hot_units = 1;
    if (p->hot_units > p->units) p->hot_units = p->units;
    p->enabled = 1;
    p->ema = calloc((size_t)layers * p->units, sizeof(float));
    fprintf(stderr,
            "[AU] cold tier armed: %d/%d bundles hot per layer "
            "(FFN %.2f GB > budget slice %.2f GB)\n",
            p->hot_units, p->units, ffn_total / 1e9,
            (double)avail / 1e9);
}

int au_filter(AuPool *p, int layer, const int *J, const float *gmag, int nJ,
              float tau_cold, unsigned char *keep) {
    if (!p->enabled) {
        memset(keep, 1, (size_t)nJ);
        p->hot_hits += nJ;
        return nJ;
    }
    float *ema = p->ema + (int64_t)layer * p->units;
    int kept = 0;
    for (int i = 0; i < nJ; i++) {
        int b = J[i] / AU_BUNDLE;
        ema[b] = 0.99f * ema[b] + 0.01f * gmag[i];
        if (b < p->hot_units) {
            keep[i] = 1;
            p->hot_hits++;
            kept++;
        } else if (gmag[i] > tau_cold) {
            /* worth a cold page-in: mmap fault will fetch the bundle */
            keep[i] = 1;
            p->cold_fetches++;
            kept++;
        } else {
            keep[i] = 0;
            p->cold_drops++;
        }
    }
    return kept;
}

void au_note_bytes_saved(AuPool *p, int64_t bytes) { p->bytes_saved += bytes; }

void au_stats_line(AuPool *p, char *buf, int n) {
    int64_t tot = p->hot_hits + p->cold_fetches + p->cold_drops;
    snprintf(buf, (size_t)n,
             "au hot=%lld cold_fetch=%lld cold_drop=%lld (%.1f%%) saved=%.2fGB",
             (long long)p->hot_hits, (long long)p->cold_fetches,
             (long long)p->cold_drops,
             tot ? 100.0 * p->cold_drops / tot : 0.0,
             p->bytes_saved / 1e9);
}

void au_free(AuPool *p) {
    free(p->ema);
    p->ema = NULL;
}

/* ---------------- shared ledger ---------------- */

typedef struct {
    char klass[24];
    int64_t bytes, hits, misses;
} LedgerRow;

static LedgerRow g_rows[8];
static int g_nrows;
static int64_t g_budget;

void au_ledger_set_budget(int64_t bytes) { g_budget = bytes; }

void au_ledger_report(const char *klass, int64_t bytes_resident,
                      int64_t hits, int64_t misses) {
    for (int i = 0; i < g_nrows; i++) {
        if (!strcmp(g_rows[i].klass, klass)) {
            g_rows[i].bytes = bytes_resident;
            g_rows[i].hits = hits;
            g_rows[i].misses = misses;
            return;
        }
    }
    if (g_nrows < 8) {
        snprintf(g_rows[g_nrows].klass, sizeof(g_rows[0].klass), "%s", klass);
        g_rows[g_nrows].bytes = bytes_resident;
        g_rows[g_nrows].hits = hits;
        g_rows[g_nrows].misses = misses;
        g_nrows++;
    }
}

void au_ledger_line(char *buf, int n) {
    int off = 0;
    int64_t tot = 0;
    for (int i = 0; i < g_nrows && off < n - 1; i++) {
        tot += g_rows[i].bytes;
        off += snprintf(buf + off, (size_t)(n - off), "%s%s=%.2fGB",
                        i ? " " : "", g_rows[i].klass, g_rows[i].bytes / 1e9);
        if (g_rows[i].hits + g_rows[i].misses > 0 && off < n - 1)
            off += snprintf(buf + off, (size_t)(n - off), "(hit %.0f%%)",
                            100.0 * g_rows[i].hits /
                            (double)(g_rows[i].hits + g_rows[i].misses));
    }
    if (off < n - 1)
        snprintf(buf + off, (size_t)(n - off), " total=%.2fGB budget=%.2fGB",
                 tot / 1e9, g_budget > 0 ? g_budget / 1e9 : 0.0);
}

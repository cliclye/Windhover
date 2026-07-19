/* budget.h — Phase 1 hard RAM ceiling on top of colibrì's soft RAM_GB plan.
 *
 * probe_hardware / compute_plan mirror coli plan / resource_plan arithmetic.
 * budget_apply_hard_cap enforces the target via:
 *   Linux  → cgroup v2 memory.max (RLIMIT_AS fallback)
 *   Windows → Job Object JOB_OBJECT_LIMIT_PROCESS_MEMORY
 *   macOS  → task_set_phys_footprint_limit, else soft_evict (90% pre-emptive)
 *
 * Lossless: no precision / router / KV policy changes. */
#ifndef KESTREL_BUDGET_H
#define KESTREL_BUDGET_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int64_t ram_total_bytes;
    int64_t ram_available_bytes;
    int64_t disk_random_read_bps;   /* 0 if not measured */
    int cores;
    int has_avx512_vnni;
    int has_gpu;
} BudgetHardware;

typedef struct {
    const char *precision_profile;  /* Phase 1: always current int4 baseline */
    int64_t resident_dense_bytes;
    int64_t expert_cache_bytes;
    int64_t kv_reserve_bytes;
    int64_t os_margin_bytes;
    int64_t target_ram_bytes;
    int kv_slots;
    const char *kv_precision;       /* Phase 1: "fp32" (unchanged) */
    const char *io_mode;            /* "buffered" | "direct" */
    const char *prefetch_mode;      /* "off" | "pilot" | "learned" */
} BudgetPlan;

/* Soft threshold before the kernel hard cap: pre-emptive expert-cache eviction. */
#define BUDGET_EVICT_FRACTION 0.90

int budget_probe_hardware(BudgetHardware *out);

/* Header-only plan arithmetic (same shape as resource_plan.build_plan RAM tier).
 * runtime_bytes should already include KV + working-set slack from the caller
 * (or pass 0 and let os_margin cover the 1.2+2.5 GB default reserve). */
int budget_compute_plan(int64_t target_ram_bytes,
                        int64_t dense_bytes,
                        int64_t runtime_bytes,
                        int kv_slots,
                        const BudgetHardware *hw,
                        BudgetPlan *out);

/* Kernel-enforced process memory ceiling. Idempotent. Returns 0 on success,
 * -1 if the platform backend could not be armed (soft plan still applies). */
int budget_apply_hard_cap(int64_t target_bytes);

/* "cgroup" | "job_object" | "rlimit" | "footprint" | "soft_evict" | "none" | "disabled" */
const char *budget_hard_cap_backend(void);

/* 1 if a hard-cap backend is available on this OS (doctor check). */
int budget_hard_cap_supported(void);

/* Active target (0 if no hard cap applied). */
int64_t budget_active_target_bytes(void);

#ifdef __cplusplus
}
#endif

#endif /* KESTREL_BUDGET_H */

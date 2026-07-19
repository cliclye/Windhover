/* tests/test_budget.c — Phase 1: probe, plan arithmetic, hard-cap arming. */
#include "../memory/budget.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;

static void expect(int cond, const char *msg){
    if(!cond){ fprintf(stderr, "FAIL: %s\n", msg); failures++; }
    else fprintf(stderr, "ok: %s\n", msg);
}

int main(void){
    BudgetHardware hw;
    expect(budget_probe_hardware(&hw) == 0, "probe_hardware returns 0");
    expect(hw.ram_total_bytes > 0 || hw.ram_available_bytes > 0,
           "probe reports some RAM");
    expect(hw.cores >= 1, "probe reports >=1 core");
    expect(budget_hard_cap_supported() == 1, "hard cap supported on this OS");

    BudgetPlan plan;
    int64_t target = (int64_t)5e9; /* above the 4GB plan floor */
    expect(budget_compute_plan(target, (int64_t)500e6, 0, 1, &hw, &plan) == 0,
           "compute_plan returns 0");
    expect(strcmp(plan.precision_profile, "int4-baseline") == 0,
           "precision stays int4-baseline");
    expect(strcmp(plan.kv_precision, "fp32") == 0, "kv precision unchanged");
    expect(plan.target_ram_bytes == target, "target preserved");
    expect(plan.expert_cache_bytes >= 0, "expert_cache non-negative");
    expect(plan.io_mode != NULL, "io_mode set");
    expect(strcmp(plan.prefetch_mode, "off") == 0 ||
           strcmp(plan.prefetch_mode, "pilot") == 0 ||
           strcmp(plan.prefetch_mode, "learned") == 0,
           "prefetch_mode valid");

    /* Hard cap: arm a generous limit so the test process itself is safe. */
    int64_t generous = hw.ram_available_bytes > 0
        ? hw.ram_available_bytes
        : (hw.ram_total_bytes > 0 ? hw.ram_total_bytes : (int64_t)8e9);
    if(generous < (int64_t)4e9) generous = (int64_t)8e9;
    int rc = budget_apply_hard_cap(generous);
    expect(rc == 0, "apply_hard_cap succeeds with generous target");
    expect(budget_active_target_bytes() == generous, "active target recorded");
    const char *be = budget_hard_cap_backend();
    expect(be && strcmp(be, "none") != 0 && strcmp(be, "disabled") != 0,
           "backend is cgroup|job_object|rlimit|footprint|soft_evict");
    fprintf(stderr, "backend=%s target=%.2f GB\n", be, generous / 1e9);

    /* COLI_HARD_CAP=0 disables. */
    setenv("COLI_HARD_CAP", "0", 1);
    expect(budget_apply_hard_cap(generous) == 0, "disabled hard cap returns 0");
    expect(strcmp(budget_hard_cap_backend(), "disabled") == 0, "backend=disabled");
    unsetenv("COLI_HARD_CAP");

    if(failures){ fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    fprintf(stderr, "test_budget: ok\n");
    return 0;
}

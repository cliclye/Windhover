/* budget.c — hardware probe + hard memory ceiling (Phase 1). */
#include "budget.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#if !defined(_WIN32)
#include <unistd.h>
#endif

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#elif defined(__APPLE__)
#include <sys/sysctl.h>
#include <sys/types.h>
#include <unistd.h>
#include <mach/mach.h>
#include <mach/vm_statistics.h>
#else
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/sysinfo.h>
#include <unistd.h>
#include <fcntl.h>
#endif

#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#if defined(_MSC_VER)
#include <intrin.h>
#else
#include <cpuid.h>
#endif
#endif

static int64_t g_active_target = 0;
static const char *g_backend = "none";
static int g_cap_applied = 0;

#if defined(_WIN32)
static HANDLE g_job = NULL;
#endif

#if !defined(_WIN32) && !defined(__APPLE__)
static char g_cgroup_path[512];
#endif

int budget_hard_cap_supported(void){
    return 1;
}

const char *budget_hard_cap_backend(void){
    if(getenv("COLI_HARD_CAP") && !atoi(getenv("COLI_HARD_CAP")))
        return "disabled";
    return g_backend;
}

int64_t budget_active_target_bytes(void){
    return g_active_target;
}

static int probe_avx512_vnni(void){
#if defined(__x86_64__) || defined(_M_X64) || defined(__i386__) || defined(_M_IX86)
#if defined(_MSC_VER)
    int info[4] = {0};
    __cpuidex(info, 7, 0);
    return (info[2] & (1 << 11)) ? 1 : 0; /* ECX bit 11 = AVX512-VNNI */
#else
    unsigned int eax=0, ebx=0, ecx=0, edx=0;
    if(!__get_cpuid_count(7, 0, &eax, &ebx, &ecx, &edx)) return 0;
    return (ecx & (1u << 11)) ? 1 : 0;
#endif
#else
    return 0;
#endif
}

static int probe_gpu(void){
    /* Never system()/fork — that dominated tiny-model CPU benches (+20–40% wall).
     * Cheap presence checks only. */
#if defined(_WIN32)
    if(GetFileAttributesA("C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe")
       != INVALID_FILE_ATTRIBUTES) return 1;
    if(GetFileAttributesA("C:\\Windows\\System32\\nvidia-smi.exe")
       != INVALID_FILE_ATTRIBUTES) return 1;
    return 0;
#else
    if(access("/dev/nvidia0", F_OK) == 0) return 1;
    if(access("/usr/bin/nvidia-smi", X_OK) == 0) return 1;
    if(access("/usr/local/bin/nvidia-smi", X_OK) == 0) return 1;
    return 0;
#endif
}

int budget_probe_hardware(BudgetHardware *out){
    if(!out) return -1;
    memset(out, 0, sizeof(*out));
    out->has_avx512_vnni = probe_avx512_vnni();
    out->has_gpu = probe_gpu();

#if defined(_WIN32)
    MEMORYSTATUSEX msx;
    memset(&msx, 0, sizeof(msx));
    msx.dwLength = sizeof(msx);
    if(GlobalMemoryStatusEx(&msx)){
        out->ram_total_bytes = (int64_t)msx.ullTotalPhys;
        out->ram_available_bytes = (int64_t)msx.ullAvailPhys;
    }
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    out->cores = (int)si.dwNumberOfProcessors;
#elif defined(__APPLE__)
    int64_t memsize = 0;
    size_t len = sizeof(memsize);
    if(sysctlbyname("hw.memsize", &memsize, &len, NULL, 0) == 0)
        out->ram_total_bytes = memsize;
    int ncpu = 0;
    len = sizeof(ncpu);
    if(sysctlbyname("hw.physicalcpu", &ncpu, &len, NULL, 0) == 0)
        out->cores = ncpu;
    else
        out->cores = (int)sysconf(_SC_NPROCESSORS_ONLN);
    {
        mach_msg_type_number_t cnt = HOST_VM_INFO64_COUNT;
        vm_statistics64_data_t vm;
        if(host_statistics64(mach_host_self(), HOST_VM_INFO64,
                             (host_info64_t)&vm, &cnt) == KERN_SUCCESS){
            double page = (double)sysconf(_SC_PAGESIZE);
            out->ram_available_bytes = (int64_t)(
                ((double)vm.free_count + (double)vm.inactive_count
                 + (double)vm.purgeable_count) * page);
        }
    }
#else
    {
        struct sysinfo si;
        if(sysinfo(&si) == 0)
            out->ram_total_bytes = (int64_t)si.totalram * (int64_t)si.mem_unit;
        FILE *f = fopen("/proc/meminfo", "r");
        if(f){
            char ln[256];
            double kb = 0;
            while(fgets(ln, sizeof(ln), f))
                if(sscanf(ln, "MemAvailable: %lf", &kb) == 1) break;
            fclose(f);
            out->ram_available_bytes = (int64_t)(kb * 1024.0);
        }
        out->cores = (int)sysconf(_SC_NPROCESSORS_ONLN);
    }
#endif
    if(out->cores < 1) out->cores = 1;
    out->disk_random_read_bps = 0; /* measured by iobench when needed; not required for Phase 1 */
    return 0;
}

int budget_compute_plan(int64_t target_ram_bytes,
                        int64_t dense_bytes,
                        int64_t runtime_bytes,
                        int kv_slots,
                        const BudgetHardware *hw,
                        BudgetPlan *out){
    if(!out) return -1;
    memset(out, 0, sizeof(*out));
    out->precision_profile = "int4-baseline";
    out->kv_precision = "fp32";
    out->prefetch_mode = "off";
    out->kv_slots = kv_slots > 0 ? kv_slots : 1;
    out->resident_dense_bytes = dense_bytes > 0 ? dense_bytes : 0;
    out->os_margin_bytes = (int64_t)(1.2e9 + 2.5e9); /* matches glm.c cap_for_ram reserves */
    out->kv_reserve_bytes = 0;
    if(runtime_bytes <= 0)
        runtime_bytes = out->os_margin_bytes;
    out->target_ram_bytes = target_ram_bytes;
    if(out->target_ram_bytes <= 0 && hw && hw->ram_available_bytes > 0)
        out->target_ram_bytes = (int64_t)(hw->ram_available_bytes * 0.88);
    if(out->target_ram_bytes < (int64_t)4e9)
        out->target_ram_bytes = (int64_t)8e9;

    int64_t remain = out->target_ram_bytes - out->resident_dense_bytes - runtime_bytes;
    out->expert_cache_bytes = remain > 0 ? remain : 0;

    /* §3.4: O_DIRECT on by default only when RAM-starved (<16GB). */
    int64_t avail = hw ? hw->ram_available_bytes : out->target_ram_bytes;
    if(avail > 0 && avail < (int64_t)16e9)
        out->io_mode = "direct";
    else
        out->io_mode = "buffered";

    return 0;
}

#if !defined(_WIN32) && !defined(__APPLE__)
static int linux_apply_cgroup(int64_t target_bytes){
    /* Prefer an existing writable cgroup (systemd user session), else try
     * creating /sys/fs/cgroup/kestrel.<pid>. Fall back to RLIMIT_AS. */
    const char *base = getenv("COLI_CGROUP_ROOT");
    char path[512];
    pid_t pid = getpid();
    if(base && *base)
        snprintf(path, sizeof(path), "%s/kestrel.%d", base, (int)pid);
    else
        snprintf(path, sizeof(path), "/sys/fs/cgroup/kestrel.%d", (int)pid);

    if(mkdir(path, 0755) != 0 && errno != EEXIST){
        /* Try under the current cgroup if we can write controllers there. */
        FILE *cf = fopen("/proc/self/cgroup", "r");
        if(!cf) return -1;
        char line[512];
        path[0] = 0;
        while(fgets(line, sizeof(line), cf)){
            /* cgroup v2: 0::/user.slice/... */
            char *p = strstr(line, "::");
            if(!p) continue;
            p += 2;
            char *nl = strchr(p, '\n'); if(nl) *nl = 0;
            snprintf(path, sizeof(path), "/sys/fs/cgroup%s/kestrel.%d", p, (int)pid);
            break;
        }
        fclose(cf);
        if(!path[0]) return -1;
        if(mkdir(path, 0755) != 0 && errno != EEXIST) return -1;
    }

    char maxp[576], procp[576];
    snprintf(maxp, sizeof(maxp), "%s/memory.max", path);
    snprintf(procp, sizeof(procp), "%s/cgroup.procs", path);
    FILE *mf = fopen(maxp, "w");
    if(!mf) return -1;
    fprintf(mf, "%lld\n", (long long)target_bytes);
    if(fclose(mf) != 0) return -1;
    FILE *pf = fopen(procp, "w");
    if(!pf) return -1;
    fprintf(pf, "%d\n", (int)pid);
    if(fclose(pf) != 0) return -1;
    snprintf(g_cgroup_path, sizeof(g_cgroup_path), "%s", path);
    g_backend = "cgroup";
    return 0;
}

static int posix_apply_rlimit(int64_t target_bytes){
    struct rlimit rl;
    rl.rlim_cur = (rlim_t)target_bytes;
    rl.rlim_max = (rlim_t)target_bytes;
    if(setrlimit(RLIMIT_AS, &rl) != 0) return -1;
    g_backend = "rlimit";
    return 0;
}
#endif

#if defined(__APPLE__)
/* macOS platform equivalent of cgroup memory.max / Job Object:
 * 1) task_set_phys_footprint_limit (public Mach API; requires entitlement/root)
 * 2) soft_evict — arm the target and rely on 90% pre-emptive expert-cache
 *    eviction (RLIMIT_AS rejects finite limits on modern Darwin). */
static int macos_apply_cap(int64_t target_bytes){
    int mb = (int)((target_bytes + (1 << 20) - 1) >> 20);
    if(mb < 256) mb = 256;
    int old = -1;
    kern_return_t kr = task_set_phys_footprint_limit(mach_task_self(), mb, &old);
    if(kr == KERN_SUCCESS){
        g_backend = "footprint";
        return 0;
    }
    /* Unprivileged processes get KERN_FAILURE / no access — still arm the
     * budget target so budget_evict_if_needed enforces the ceiling. */
    g_backend = "soft_evict";
    fprintf(stderr, "[BUDGET] macOS footprint limit unavailable (%s); "
            "using soft_evict at %.0f%% of target\n",
            mach_error_string(kr), BUDGET_EVICT_FRACTION * 100.0);
    return 0;
}
#endif

#if defined(_WIN32)
static int windows_apply_job(int64_t target_bytes){
    if(!g_job){
        g_job = CreateJobObjectA(NULL, NULL);
        if(!g_job) return -1;
    }
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION info;
    memset(&info, 0, sizeof(info));
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    info.ProcessMemoryLimit = (SIZE_T)target_bytes;
    if(!SetInformationJobObject(g_job, JobObjectExtendedLimitInformation,
                                &info, sizeof(info)))
        return -1;
    if(!AssignProcessToJobObject(g_job, GetCurrentProcess())){
        DWORD err = GetLastError();
        if(err != ERROR_ACCESS_DENIED) return -1;
    }
    g_backend = "job_object";
    return 0;
}
#endif

int budget_apply_hard_cap(int64_t target_bytes){
    if(getenv("COLI_HARD_CAP") && !atoi(getenv("COLI_HARD_CAP"))){
        g_backend = "disabled";
        g_active_target = 0;
        return 0;
    }
    if(target_bytes < (int64_t)(256 * 1024 * 1024)) /* refuse absurdly small */
        return -1;
    if(g_cap_applied && g_active_target == target_bytes)
        return 0;

    int rc = -1;
#if defined(_WIN32)
    rc = windows_apply_job(target_bytes);
#elif defined(__APPLE__)
    rc = macos_apply_cap(target_bytes);
#else
    rc = linux_apply_cgroup(target_bytes);
    if(rc != 0)
        rc = posix_apply_rlimit(target_bytes);
#endif
    if(rc == 0){
        g_active_target = target_bytes;
        g_cap_applied = 1;
        fprintf(stderr, "[BUDGET] hard cap %.2f GB via %s (pre-emptive evict at %.0f%%)\n",
                target_bytes / 1e9, g_backend, BUDGET_EVICT_FRACTION * 100.0);
    } else {
        fprintf(stderr, "[BUDGET] WARNING: could not arm hard memory cap "
                "(soft RAM_GB plan still applies)\n");
        g_backend = "none";
    }
    return rc;
}

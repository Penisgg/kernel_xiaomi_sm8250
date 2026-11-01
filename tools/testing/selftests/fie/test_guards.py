#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test actual FIE admission/recovery code and legacy request flag mapping."""
import pathlib
import subprocess
import tempfile
import unittest

from test_runtime import ROOT, function


class GuardTests(unittest.TestCase):
    def test_domain_pmu_and_sample_recovery(self):
        names = (
            "static struct throt_data *fie_cpu_domain(",
            "static bool fie_domain_ready(",
            "static bool fie_pmu_event_valid(",
            "static void release_perf_events(",
            "static int create_perf_events(",
            "static bool pmu_get_stats(",
            "static void reset_sfd_data(struct sfd_data *sfd)\n{",
            "static void reset_htd_data(struct htd_data *htd)\n{",
            "static bool pmu_update_stats(",
            "static int fie_cpuhp_up(",
        )
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
typedef uint64_t u64;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, value) ((x) = (value))
#define smp_load_acquire(ptr) (*(ptr))
#define per_cpu(var, cpu) var[cpu]
#define likely(x) (x)
#define unlikely(x) (x)
#define PERF_EVENT_STATE_ACTIVE 1
#define PERF_HES_STOPPED 1
#define PERF_TYPE_RAW 4
#define ARMV8_PMUV3_PERFCTR_CPU_CYCLES 17
#define PMU_EVT_MAX 1
#define CPU_CYCLES 0
#define ERR_PTR(err) ((void *)(intptr_t)(err))
#define IS_ERR(ptr) ((uintptr_t)(ptr) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(ptr) (!(ptr) || IS_ERR(ptr))
#define PTR_ERR(ptr) ((int)(intptr_t)(ptr))
static int irqs, created, released, installed, warnings;
#define local_irq_save(flags) do { (flags) = irqs; irqs = 1; } while (0)
#define local_irq_restore(flags) do { irqs = (flags); } while (0)
#define local_irq_disable() do { assert(!irqs); irqs = 1; } while (0)
#define local_irq_enable() do { assert(irqs); irqs = 0; } while (0)
#define raw_spin_lock(lock) do { } while (0)
#define raw_spin_unlock(lock) do { } while (0)
#define fie_stat_inc(cpu, member) do { } while (0)
#define pr_warn_ratelimited(...) do { warnings++; } while (0)
struct perf_event { int state, oncpu; struct { int idx, state; } hw; };
struct perf_event_attr { int type, size, pinned, config1, config; };
struct cpu_pmu_evt { struct perf_event *pev[PMU_EVT_MAX]; };
static struct cpu_pmu_evt pevt_pcpu[1];
static const unsigned int pmu_evt_id[PMU_EVT_MAX] = {17};
static struct perf_event event;
static int create_error;
static struct perf_event *create_pev(struct perf_event_attr *attr, int cpu)
{ assert(attr->pinned && cpu == 0); created++; return create_error ? ERR_PTR(-EIO) : &event; }
static void perf_event_release_kernel(struct perf_event *ev)
{ assert(!irqs && ev == &event); released++; }
struct pmu_stat { u64 cntpct, const_cyc, cpu_cyc; };
struct sfd_data { int lock; u64 cpu_cyc, const_cyc; bool stale; };
struct htd_data { u64 start, cpu_cyc, const_cyc; };
struct cpu_pmu {
    bool needs_rebase;
    struct pmu_stat *cur_ptr[2], cur[2];
    struct sfd_data sfd;
    struct htd_data htd;
};
static struct cpu_pmu cpu_pmu_evs[1];
static bool cpu_has_amu[1], cpu_has_amu_const[1], fie_cpu_ready[1];
static unsigned int cpu_max_freq[1];
static void *domain_throt_data[1];
static struct pmu_stat sample;
static int raw_reads;
static int raw_smp_processor_id(void) { return 0; }
static bool cpu_supports_amu_const(int cpu) { return cpu_has_amu_const[cpu]; }
static void fie_pmu_read(struct pmu_stat *stat) { assert(irqs); raw_reads++; *stat = sample; }
static void fie_amu_read(struct pmu_stat *stat) { *stat = sample; }
static void fie_amu_const_read(struct pmu_stat *stat) { *stat = sample; }
#define pmu_read_cur_ptrs(pmu, a, b) do { (a) = &(pmu)->cur[0]; (b) = &(pmu)->cur[1]; } while (0)
#define pmu_get_cur_writer(pmu) (&(pmu)->cur[0])
#define pmu_put_cur_writer(pmu, cur) do { } while (0)
static int fie_sfd;
#define cpumask_of(cpu) NULL
static void topology_set_scale_freq_source(void *data, void *mask) { installed++; }
static void set_cpu_hw_throttle_idle(int cpu, bool idle) { assert(!idle); }
'''
        code += "\n".join(function("kernel/sched/fie.c", name) for name in names)
        code += r'''
static void reset(void)
{
    event = (struct perf_event){ .state = 1, .oncpu = 0, .hw.idx = 0 };
    create_error = irqs = created = released = installed = warnings = raw_reads = 0;
    fie_cpu_ready[0] = false;
    domain_throt_data[0] = &event;
    cpu_max_freq[0] = 1000000;
    sample = (struct pmu_stat){100, 100, 100};
}
int main(void)
{
    reset(); domain_throt_data[0] = NULL;
    assert(!fie_domain_ready(0)); assert(fie_cpuhp_up(0) == 0);
    assert(!created && !installed && !fie_cpu_ready[0]);
    reset(); cpu_max_freq[0] = 0;
    assert(!fie_domain_ready(0)); assert(fie_cpuhp_up(0) == 0);
    assert(!created && !installed && !fie_cpu_ready[0]);
    reset(); event.hw.idx = 2;
    assert(fie_cpuhp_up(0) == 0);
    assert(created == 1 && released == 1 && !pevt_pcpu[0].pev[0]);
    assert(!installed && !raw_reads && !fie_cpu_ready[0]);
    reset(); event.state = -2;
    assert(fie_cpuhp_up(0) == 0);
    assert(released == 1 && !raw_reads && !fie_cpu_ready[0]);
    reset(); create_error = 1;
    assert(fie_cpuhp_up(0) == 0);
    assert(!released && !installed && !fie_cpu_ready[0]);
    reset(); assert(fie_cpuhp_up(0) == 0);
    assert(installed == 1 && fie_cpu_ready[0] && raw_reads == 1);
    assert(!fie_pmu_event_valid(NULL, 0));
    event.oncpu = 1; assert(!fie_pmu_event_valid(&event, 0)); event.oncpu = 0;
    event.hw.state = PERF_HES_STOPPED; assert(!fie_pmu_event_valid(&event, 0));
    event.hw.state = 0;

    struct cpu_pmu *pmu = &cpu_pmu_evs[0];
    struct pmu_stat cur, prev;
    pmu->sfd.cpu_cyc = 123; pmu->sfd.const_cyc = 456; pmu->sfd.stale = true;
    pmu->htd.start = pmu->htd.cpu_cyc = pmu->htd.const_cyc = 123;
    irqs = 1; event.hw.idx = 2;
    assert(!pmu_update_stats(0, pmu, &cur, &prev));
    assert(raw_reads == 1 && pmu->needs_rebase);
    assert(!pmu->sfd.cpu_cyc && !pmu->sfd.const_cyc && !pmu->sfd.stale);
    assert(!pmu->htd.cpu_cyc && !pmu->htd.const_cyc && !pmu->htd.start);
    event.hw.idx = 0; sample = (struct pmu_stat){10000, 10000, 50000};
    assert(pmu_update_stats(0, pmu, &cur, &prev));
    assert(!pmu->needs_rebase && cur.cpu_cyc == prev.cpu_cyc && cur.const_cyc == prev.const_cyc);
    sample.cpu_cyc += 100; sample.const_cyc += 10;
    assert(pmu_update_stats(0, pmu, &cur, &prev));
    assert(cur.cpu_cyc - prev.cpu_cyc == 100 && cur.const_cyc - prev.const_cyc == 10);
    /* Recovery through idle-exit (no previous sample requested). */
    event.state = 0; assert(!pmu_update_stats(0, pmu, &cur, NULL));
    event.state = 1; assert(pmu_update_stats(0, pmu, &cur, NULL));
    assert(!pmu->needs_rebase);
    irqs = 0; release_perf_events(0); assert(released == 1);
    return 0;
}
'''
        self.compile_and_run(code)

    def test_legacy_pm_flags(self):
        text = (ROOT / "block/blk-core.c").read_text()
        start = text.index("\trq->rq_flags = rq_flags;")
        mapping = text[start:text.index("\n\t/* init elvpriv */", start)]
        code = r'''
#include <assert.h>
#define BLK_MQ_REQ_PREEMPT (1U << 3)
#define BLK_MQ_REQ_PM (1U << 4)
#define RQF_PREEMPT (1U << 7)
#define RQF_PM (1U << 15)
static unsigned int map(unsigned int flags)
{
    struct { unsigned int rq_flags; } request, *rq = &request;
    unsigned int rq_flags = 0;
'''
        code += mapping + r'''
    return rq->rq_flags;
}
int main(void)
{
    assert(map(0) == 0);
    assert(map(BLK_MQ_REQ_PM) == RQF_PM);
    assert(map(BLK_MQ_REQ_PREEMPT) == RQF_PREEMPT);
    assert(map(BLK_MQ_REQ_PREEMPT | BLK_MQ_REQ_PM) == (RQF_PREEMPT | RQF_PM));
}
'''
        self.compile_and_run(code)

    def compile_and_run(self, code):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "guards.c"
            exe = pathlib.Path(tmp) / "guards"
            source.write_text(code)
            subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Werror", str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()

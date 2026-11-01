#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Run the actual state helpers with host mocks; hardware tests are separate."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]


def function(path, signature):
    text = (ROOT / path).read_text()
    start = text.index(signature)
    end = text.index("\n}", start) + 2
    return text[start:end]


class RuntimeTests(unittest.TestCase):
    def test_idle_and_irq_state(self):
        domain = function("kernel/sched/fie.c", "static struct throt_data *fie_cpu_domain(")
        idle = function("kernel/sched/fie.c", "static void set_cpu_hw_throttle_idle(")
        irq = function("drivers/cpufreq/qcom-cpufreq-hw.c", "static void qcom_lmh_set_irq(")
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <limits.h>
#include <stddef.h>
typedef unsigned int cpumask_t;
struct throt_data { cpumask_t idle_cpus, cpus; int idle_cpu_lock, throt_lock; };
static struct throt_data *domains[3];
#define domain_throt_data domains
#define per_cpu(var, cpu) var[cpu]
#define smp_load_acquire(ptr) (*(ptr))
#define raw_spin_lock_irqsave(lock, flags) do { (flags) = 0; } while (0)
#define raw_spin_unlock_irqrestore(lock, flags) do { (void)(flags); } while (0)
#define raw_spin_lock(lock) do { } while (0)
#define raw_spin_unlock(lock) do { } while (0)
#define CPU_HW_THROTTLE 1
static int clears;
static void update_thermal_pressure(struct throt_data *t, int src, unsigned int cap)
{ assert(t && src == CPU_HW_THROTTLE && cap == UINT_MAX); clears++; }
static bool cpumask_test_and_set_cpu(int cpu, cpumask_t *mask)
{ bool old = *mask & (1U << cpu); *mask |= 1U << cpu; return old; }
static void cpumask_clear_cpu(int cpu, cpumask_t *mask) { *mask &= ~(1U << cpu); }
static bool cpumask_equal(cpumask_t *a, cpumask_t *b) { return *a == *b; }
struct cpufreq_qcom { bool irq_disabled; int dcvsh_irq; };
static int depth;
static void enable_irq(int irq) { assert(irq == 1); assert(depth == 1); depth--; }
static void disable_irq_nosync(int irq) { assert(irq == 1); assert(depth == 0); depth++; }
'''
        source += domain + "\n" + idle + "\n" + irq + r'''
int main(void)
{
    /* Every successful CPU subset; the rest model offline/failed PMU CPUs. */
    for (unsigned int online = 0; online < 8; online++) {
        struct throt_data t = { .cpus = 7, .idle_cpus = 7 };
        clears = 0;
        for (int cpu = 0; cpu < 3; cpu++) domains[cpu] = &t;
        for (int cpu = 0; cpu < 3; cpu++) if (online & (1U << cpu)) {
            set_cpu_hw_throttle_idle(cpu, false);
            set_cpu_hw_throttle_idle(cpu, false);
        }
        assert(t.idle_cpus == (7U & ~online));
        for (int cpu = 0; cpu < 3; cpu++) if (online & (1U << cpu)) {
            set_cpu_hw_throttle_idle(cpu, true);
            set_cpu_hw_throttle_idle(cpu, true);
        }
        assert(t.idle_cpus == 7);
        assert(clears == !!online);
        /* Another hotplug/idle cycle must clear again, with no underflow. */
        set_cpu_hw_throttle_idle(0, false);
        set_cpu_hw_throttle_idle(0, true);
        assert(clears == !!online + 1);
    }
    /* All serialized orders of mask/unmask, including repeated requests. */
    for (unsigned int sequence = 0; sequence < 256; sequence++) {
        struct cpufreq_qcom c = { .dcvsh_irq = 1 };
        depth = 0;
        for (int i = 0; i < 8; i++) {
            qcom_lmh_set_irq(&c, !!(sequence & (1U << i)));
            assert(depth == c.irq_disabled);
        }
        qcom_lmh_set_irq(&c, true);
        assert(depth == 0);
    }
    domains[0] = NULL;
    set_cpu_hw_throttle_idle(0, true);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c = pathlib.Path(tmp) / "state.c"
            exe = pathlib.Path(tmp) / "state"
            c.write_text(source)
            subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Werror", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()

.. SPDX-License-Identifier: GPL-2.0

FIE diagnostics and validation
==============================

FIE keeps each frequency domain's idle CPU mask under its idle lock. All
members start idle; a CPU becomes busy only after successful FIE bring-up.
Offline CPUs and CPUs whose PMU setup failed remain idle. Repeated idle or
hotplug notifications do not change the mask twice. The measured hardware
thermal cap is cleared when the last busy member enters idle or goes offline.
The independent cpufreq/LMh thermal cap remains in effect.

Optional diagnostics
--------------------

Merge ``vendor/xiaomi/fie-debug.config`` after the device defconfig and
``vendor/xiaomi/magictime-common.config`` to enable debugfs diagnostics. This
fragment is intended for debug builds. With build.sh, set ``FIE_DEBUG=1``
in settings.sh to include this fragment. With CONFIG_DEBUG_FS disabled, the
statistics and their update instructions are omitted.

With debugfs mounted at ``/sys/kernel/debug``, root can read ``fie_stats``.
Each row contains a CPU ID followed by:

* ``ready``: whether that CPU completed FIE initialization;
* ``domain_ready``: whether its frequency domain has been published with a
  nonzero maximum frequency;
* ``pmu_failures``: failed attempts to create or validate that CPU's perf
  counters (including inactive events or the wrong hardware counter);
* ``skipped_hooks``: scheduler, idle or tick hooks skipped because a CPU is
  inactive or FIE is not ready (remote-runqueue checks count on the caller);
* ``zero_cycle_samples``: otherwise long-enough hardware-throttle samples
  discarded because no CPU cycles were counted;
* ``freq_updates``: successful frequency-scale updates;
* ``invalid_pmu_samples``: attempted reads skipped because the perf event was
  not active on this CPU's dedicated cycle counter.

Counters are cumulative across CPU hotplug. The file is a live snapshot,
not an atomic snapshot of all CPUs. Skipped hooks around hotplug are expected.
No counters are reset by reading the file. A nonzero ready flag together with
increasing freq_updates under load confirms that the measurement path runs.

Counter and frequency-domain admission
--------------------------------------

The PMUv3 driver may allocate a general counter when PMCCNTR_EL0 is busy.
FIE's direct PMCCNTR_EL0 read is permitted only for an active, running event
on the local CPU at the driver's dedicated cycle-counter index (zero).
Unsuitable events are released and CPU bring-up still succeeds without FIE.
The event is checked again before every direct PMU read. If it becomes
unusable, accumulated measurements are discarded; the first valid reading
becomes a new baseline so the unavailable interval is not counted.

An absent domain or zero maximum frequency prevents FIE bring-up on that CPU.
The cpufreq fallback remains available. If a domain is registered later, FIE
can retry on the next CPU online cycle; it does not force CPU hotplug itself.
Hooks also check domain readiness before doing frequency calculations.

Validation
----------

Host checks, run from the source root::

    python3 tools/testing/selftests/fie/test_build.py
    python3 tools/testing/selftests/fie/test_runtime.py
    python3 tools/testing/selftests/fie/test_guards.py
    bash -n build.sh

The guard checks cover wrong/inactive counters, CPU mismatch, absent/zero
frequency domains, failed-event cleanup, recovery without counting the invalid
interval, and the legacy block request PM flag mapping.

The build checks mock make, packaging and publication: they do not use the
network or publish messages. The runtime checks compile the actual idle and
IRQ state helpers against host mocks. They cover idle/hotplug accounting and
IRQ disable depth, not real interrupt concurrency or hardware behavior.

On both alioth and munch, validate a full boot and sustained load, repeated
screen-off suspend/resume, and CPU offline/online cycles. Check that frequency
updates resume after online and that LMh interrupts/polling still respond to
thermal throttling. Exercise a forced PMU-creation failure in a test build:
CPU bring-up must succeed, ready must remain zero for the affected CPU, and
other CPUs' frequency updates and domain idle accounting must continue.
Lockdep/KASAN test builds are useful for IRQ/workqueue and hotplug stress.

Build artifacts
---------------

build.sh uses a separate output directory for each device under
``${OUT_ROOT:-$KERNEL/out}``. It removes previously generated Image, DTBO and
DTB files before compilation. Configuration, compiler, logging or artifact
validation failures stop the build before ZIP packaging. DTBs are concatenated
in lexical path order. Existing Telegram publishing runs only after successful
compilation, artifact validation and ZIP packaging.

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
* ``pmu_failures``: failed attempts to create that CPU's perf counters;
* ``skipped_hooks``: scheduler, idle or tick hooks skipped because a CPU is
  inactive or FIE is not ready (remote-runqueue checks count on the caller);
* ``zero_cycle_samples``: otherwise long-enough hardware-throttle samples
  discarded because no CPU cycles were counted;
* ``freq_updates``: successful frequency-scale updates.

Counters are cumulative across CPU hotplug. The file is a live snapshot,
not an atomic snapshot of all CPUs. Skipped hooks around hotplug are expected.
No counters are reset by reading the file. A nonzero ready flag together with
increasing freq_updates under load confirms that the measurement path runs.

Validation
----------

Host checks, run from the source root::

    python3 tools/testing/selftests/fie/test_build.py
    python3 tools/testing/selftests/fie/test_runtime.py
    bash -n build.sh

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

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exercise build.sh without downloading tools, changing git, or publishing."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
SCRIPT = (ROOT / "build.sh").read_text()
FUNCTIONS = SCRIPT[SCRIPT.index("# Return the actual"):SCRIPT.index('\ncheck_and_wget "$CLANG"')]


class BuildTests(unittest.TestCase):
    def run_build(self, mode):
        with tempfile.TemporaryDirectory(prefix="kernel build ") as tmp:
            root = pathlib.Path(tmp)
            kernel = root / "kernel"
            kernel.mkdir()
            (root / "settings.sh").write_text("LAST=old\nBUILD=1\n")
            package = root / "MagicTime-alioth"
            package.mkdir()
            boot = kernel / "out/alioth/arch/arm64/boot"
            (boot / "dts").mkdir(parents=True)
            for name in ("Image", "dtbo.img", "dts/stale.dtb"):
                (boot / name).write_text("stale")
            # All subprocesses are local mocks; no credentials or network used.
            mocks = r'''
KERNEL=$PWD
MAIN=$(dirname "$PWD")
DEVICE=alioth TYPE=test FILE=test BUILD=1 LAST=old VERSION=test
BUILD_DATE=test DESC=test PREFIX= VERBOSE=0
export MODE
if [[ "$MODE" == debug ]]; then FIE_DEBUG=1; fi
make() {
    if [[ " $* " == *" alioth_defconfig "* ]]; then
        if [[ "$MODE" == debug ]]; then
            [[ " $* " == *" vendor/xiaomi/fie-debug.config "* ]] || return 1
        fi
        [[ "$MODE" != config_fail ]]
        return
    fi
    [[ "$MODE" != make_fail ]] || { echo 'compiler crashed'; return 7; }
    [[ "$MODE" != missing ]] || return 0
    local boot="$OUT/arch/arm64/boot"
    printf fresh > "$boot/Image"
    printf overlay > "$boot/dtbo.img"
    [[ "$MODE" != no_dtb ]] || return 0
    printf B > "$boot/dts/b.dtb"
    printf A > "$boot/dts/a.dtb"
    [[ "$MODE" != empty_dtb ]] || : > "$boot/dts/a.dtb"
}
tee() {
    if [[ "$MODE" == tee_fail ]]; then cat >/dev/null; return 1; fi
    command tee "$@"
}
find() {
    if [[ "$MODE" == find_fail && " $* " == *" -print0 "* ]]; then return 1; fi
    command find "$@"
}
sort() {
    [[ "$MODE" != sort_fail ]] || return 1
    command sort "$@"
}
git() { echo local; }
7z() { echo package >> "$MAIN/actions"; [[ "$MODE" != zip_fail ]]; }
curl() { echo publish >> "$MAIN/actions"; }
'''
            result = subprocess.run(
                ["bash", "-c", FUNCTIONS + mocks +
                 '\nif build; then exit 0; else exit 1; fi'],
                cwd=kernel, env={**os.environ, "MODE": mode},
                text=True, capture_output=True,
            )
            actions = (root / "actions").read_text() if (root / "actions").exists() else ""
            if mode in ("ok", "debug"):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual((package / "Image").read_text(), "fresh")
                self.assertEqual((package / "dtb").read_text(), "AB")
                self.assertIn("publish", actions)
            else:
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("publish", actions)
                if mode != "zip_fail":
                    self.assertNotIn("package", actions)

    def test_build_and_packaging(self):
        for mode in ("ok", "debug", "config_fail", "make_fail", "tee_fail", "missing",
                     "no_dtb", "empty_dtb", "zip_fail", "find_fail", "sort_fail"):
            with self.subTest(mode=mode):
                self.run_build(mode)


if __name__ == "__main__":
    unittest.main()

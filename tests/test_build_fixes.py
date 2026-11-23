"""Offline integration tests: no Android build, device, network, or hardware I/O."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixes', REPO / 'build/apply_fixes.py')
fixes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixes)

DRM = """#define DEFAULT_NUM_LMS 2
static uint32_t number_of_lms = DEFAULT_NUM_LMS;
src_w = width/number_of_lms;
crtc_w = width/number_of_lms;
"""
ACTION = """int GUIAction::flashlightImpl(std::string arg) {
    if (TWFunc::Path_Exists("/sys/class/leds/flashlight/brightness")) {
        path_one = "/sys/class/leds/flashlight";
    }
    TWFunc::write_to_file(bright_one, max_brt_one);
}
"""
SERVICE = """on boot

service recovery /system/bin/recovery
    socket recovery stream 422 system system
    seclabel u:r:recovery:s0
"""
ETC_MAKE = """include $(CLEAR_VARS)
LOCAL_MODULE := init.recovery.service.rc
LOCAL_SRC_FILES := init.recovery.service22.rc
include $(BUILD_PREBUILT)
"""


class BuildFixes(unittest.TestCase):
    def setUp(self):
        base = REPO / 'tests/.work'
        base.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='integration-', dir=base)
        self.root = Path(self.tmp.name).resolve()
        self.root.relative_to(base.resolve())  # Verify owned recursive cleanup stays inside test workspace.
        self.tree = self.root / 'device/realme/spaced'
        for name in ('BoardConfig.mk', 'device.mk', 'vendorsetup.sh', 'build/apply_fixes.py', 'build/fixes.mk',
                     'recovery/root/init.recovery.mt6781.rc', 'recovery/root/init.recovery.n50-torch.rc',
                     'prebuilt/manifest.json'):
            target = self.tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        for name in fixes.KERNEL_HASHES:
            src, dst = REPO / 'prebuilt' / name, self.tree / 'prebuilt' / name
            try: os.link(src, dst)
            except OSError: shutil.copyfile(src, dst)
        self.put('build/envsetup.sh', '# mock source checkout\n')
        self.put('bootable/recovery/minuitwrp/graphics_drm.cpp', DRM)
        self.put('bootable/recovery/gui/action.cpp', ACTION)
        self.put('bootable/recovery/etc/init.recovery.service22.rc', SERVICE)
        self.put('bootable/recovery/etc/Android.mk', ETC_MAKE)

    def tearDown(self): self.tmp.cleanup()

    def put(self, relative, text):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode())
        return p

    def test_apply_verify_idempotence(self):
        fixes.prepare(self.root, self.tree)
        fixes.prepare(self.root, self.tree, verify=True)
        first = {p: (self.root / p).read_bytes() for p in fixes.TRANSFORMS}
        marker = (self.root / fixes.MARKER).read_bytes()
        fixes.prepare(self.root, self.tree)
        self.assertEqual(first, {p: (self.root / p).read_bytes() for p in fixes.TRANSFORMS})
        self.assertEqual(marker, (self.root / fixes.MARKER).read_bytes())
        self.assertIn('#define DEFAULT_NUM_LMS 1', first['bootable/recovery/minuitwrp/graphics_drm.cpp'].decode())
        self.assertIn(fixes.PRELOAD, first['bootable/recovery/etc/init.recovery.service22.rc'].decode())

    def test_verify_never_writes_unprepared_source(self):
        before = {p: (self.root / p).read_bytes() for p in fixes.TRANSFORMS}
        with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree, verify=True)
        self.assertEqual(before, {p: (self.root / p).read_bytes() for p in fixes.TRANSFORMS})
        self.assertFalse((self.root / fixes.MARKER).exists())

    def test_validate_all_sources_before_any_write(self):
        self.put('bootable/recovery/gui/action.cpp', ACTION.replace('flashlightImpl', 'changedUpstream'))
        before = {p: (self.root / p).read_bytes() for p in fixes.TRANSFORMS}
        with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree)
        self.assertEqual(before, {p: (self.root / p).read_bytes() for p in fixes.TRANSFORMS})

    def test_duplicate_or_changed_drm_defaults_refused(self):
        for changed in (DRM + '#define DEFAULT_NUM_LMS 2\n', DRM.replace('DEFAULT_NUM_LMS 2', 'DEFAULT_NUM_LMS 20')):
            with self.assertRaises(ValueError): fixes.one_plane(changed)

    def test_other_preload_refused(self):
        self.put('bootable/recovery/etc/init.recovery.service22.rc', SERVICE + '    setenv LD_PRELOAD /system/lib64/libother.so\n')
        with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree)

    def test_changed_service_packaging_refused(self):
        self.put('bootable/recovery/etc/Android.mk', ETC_MAKE.replace('service22', 'service33'))
        with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree)

    def test_kernel_bundle_digest_required(self):
        # Replace only the fixture name, never mutate a hardlinked original kernel.
        bad = self.tree / 'prebuilt/bad-kernel'
        bad.write_bytes(b'wrong kernel')
        bad.replace(self.tree / 'prebuilt/Image.gz')
        with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree)
        self.assertEqual(hashlib.sha256((REPO / 'prebuilt/Image.gz').read_bytes()).hexdigest(), fixes.KERNEL_HASHES['Image.gz'])

    def test_changed_source_invalidates_marker(self):
        fixes.prepare(self.root, self.tree)
        with (self.root / 'bootable/recovery/gui/action.cpp').open('ab') as f: f.write(b'\n// later source change\n')
        with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree, verify=True)

    def test_source_symlink_cannot_escape_checkout(self):
        outside = self.root.parent / (self.root.name + '-outside.cpp')
        outside.write_bytes(DRM.encode())
        target = self.root / 'bootable/recovery/minuitwrp/graphics_drm.cpp'
        target.unlink()
        try:
            target.symlink_to(outside)
            with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree)
        finally: outside.unlink()

    def test_marker_symlink_refused_before_source_write(self):
        outside = self.root.parent / (self.root.name + '-marker')
        outside.write_bytes(b'untouched')
        target = self.root / fixes.MARKER
        try:
            target.symlink_to(outside)
            with self.assertRaises(ValueError): fixes.prepare(self.root, self.tree)
            self.assertEqual((self.root / 'bootable/recovery/minuitwrp/graphics_drm.cpp').read_text(), DRM)
            self.assertEqual(outside.read_bytes(), b'untouched')
        finally: outside.unlink()

    def test_hook_runs_with_envsetup_gettop(self):
        result = subprocess.run(['bash', '-c', 'gettop() { printf "%s\\n" "' + str(self.root) + '"; }; '
                                 'source "' + str(self.tree / 'vendorsetup.sh') + '"'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        fixes.prepare(self.root, self.tree, verify=True)

    def test_make_gate_rejects_missing_hook_and_accepts_prepared_source(self):
        makefile = self.put('Gate.mk', 'DEVICE_PATH := device/realme/spaced\ninclude $(DEVICE_PATH)/build/fixes.mk\nall:\n\t@echo BUILD_GATE_PASS\n')
        bad = subprocess.run(['make', '-f', str(makefile)], cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        fixes.prepare(self.root, self.tree)
        good = subprocess.run(['make', '-f', str(makefile)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn('BUILD_GATE_PASS', good.stdout)

    def test_torch_packaging(self):
        module = (REPO / 'torch/Android.mk').read_text()
        self.assertIn('LOCAL_MULTILIB := 64', module)
        self.assertIn('LOCAL_SHARED_LIBRARIES := libc libdl', module)
        init = (REPO / 'recovery/root/init.recovery.n50-torch.rc').read_text()
        self.assertIn('/brightness 0', init)
        self.assertNotIn('/dev/flashlight', init)
        self.assertNotIn('LD_PRELOAD', init)


if __name__ == '__main__': unittest.main(verbosity=2)

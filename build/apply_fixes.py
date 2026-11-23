#!/usr/bin/env python3
"""Prepare OrangeFox source fixes; --verify checks them without writing."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SCHEMA = 1
KERNEL_HASHES = {
    'Image.gz': '31be7af9a33a2bbf4d50f92ed52004c56c143fc084f8c172564f53bcf63ccc60',
    'dtb.img': 'c4369708c44832a5160717eaca9aab40f0c75e0eb4a7453d106cd17e036e0e12',
    'dtbo.img': '949fe6a692704496912701218a058d9304ac74096c04f4a9f478802c2a0106e7',
}
TORCH_DIR = '/tmp/n50_torch_/flashlight'
PRELOAD = '    setenv LD_PRELOAD /system/lib64/libn50_torch.so'
MARKER = 'bootable/recovery/.n50-spaced-fixes.json'


def require(ok, message):
    if not ok: raise ValueError(message)

def digest(data): return hashlib.sha256(data).hexdigest()

def contained(root, path):
    resolved = path.resolve()
    try: resolved.relative_to(root)
    except ValueError: raise ValueError('path escapes the source checkout: ' + str(path))
    require(resolved.is_file(), 'missing required file: ' + str(path))
    return resolved


def replace_once(text, old, new, label):
    if text.count(old) == 1 and text.count(new) == 0:
        return text.replace(old, new, 1)
    require(text.count(old) == 0 and text.count(new) == 1, label + ': missing, duplicate or conflicting source context')
    return text


def one_plane(text):
    require('static uint32_t number_of_lms = DEFAULT_NUM_LMS;' in text, 'DRM default initialization changed')
    require('src_w = width/number_of_lms;' in text and 'crtc_w = width/number_of_lms;' in text,
            'DRM plane-width calculations changed; review upstream before building')
    old = '#define DEFAULT_NUM_LMS 2'
    new = '#define DEFAULT_NUM_LMS 1 // spaced: one full-width DRM plane for legacy fbdev addons'
    definitions = re.findall(r'^\s*#define\s+DEFAULT_NUM_LMS.*$', text, re.M)
    require(definitions == [old] or definitions == [new], 'unsupported or duplicate DRM default definition')
    return replace_once(text, old, new, 'DRM one-plane default')


def torch_paths(text):
    require('GUIAction::flashlightImpl' in text and 'TWFunc::write_to_file(bright_one, max_brt_one)' in text,
            'OrangeFox torch action/write path changed')
    text = replace_once(text, '"/sys/class/leds/flashlight/brightness"', '"' + TORCH_DIR + '/brightness"', 'torch probe path')
    return replace_once(text, '"/sys/class/leds/flashlight"', '"' + TORCH_DIR + '"', 'torch state path')


def torch_preload(text):
    service = 'service recovery /system/bin/recovery'
    require(text.count(service) == 1, 'recovery service definition changed')
    preloads = re.findall(r'^\s*setenv\s+LD_PRELOAD\s+(.+)$', text, re.M)
    if preloads:
        require(preloads == ['/system/lib64/libn50_torch.so'],
                'unexpected recovery preload')
        require(text.count(PRELOAD) == 1, 'unexpected torch preload layout')
        return text
    return text.replace(service, service + '\n' + PRELOAD, 1)


TRANSFORMS = {
    'bootable/recovery/minuitwrp/graphics_drm.cpp': one_plane,
    'bootable/recovery/gui/action.cpp': torch_paths,
    'bootable/recovery/etc/init.recovery.service22.rc': torch_preload,
}


def validate_tree(root, tree):
    require(tree == (root / 'device/realme/spaced').resolve(), 'tree must be installed at device/realme/spaced')
    contained(root, root / 'build/envsetup.sh')
    for name, expected in KERNEL_HASHES.items():
        path = contained(root, tree / 'prebuilt' / name)
        require(digest(path.read_bytes()) == expected, 'known-working kernel bundle mismatch: ' + name)
    manifest = json.loads(contained(root, tree / 'prebuilt/manifest.json').read_text(encoding='utf-8'))
    require(manifest['files'] == KERNEL_HASHES, 'kernel checksum manifest changed')
    board = contained(root, tree / 'BoardConfig.mk').read_text(encoding='utf-8')
    for token in ('TARGET_PREBUILT_KERNEL := $(DEVICE_PATH)/prebuilt/Image.gz',
                  'TARGET_PREBUILT_DTB := $(DEVICE_PATH)/prebuilt/dtb.img',
                  'BOARD_PREBUILT_DTBOIMAGE := $(DEVICE_PATH)/prebuilt/dtbo.img'):
        require(token in board, 'kernel configuration changed: ' + token)
    init = contained(root, tree / 'recovery/root/init.recovery.mt6781.rc').read_text(encoding='utf-8')
    require(init.count('import /init.recovery.n50-torch.rc') == 1, 'missing/duplicate torch init import')
    state = contained(root, tree / 'recovery/root/init.recovery.n50-torch.rc').read_text(encoding='utf-8')
    require('write ' + TORCH_DIR + '/brightness 0' in state and 'write ' + TORCH_DIR + '/max_brightness 1' in state,
            'torch startup state must be OFF with maximum 1')
    device = contained(root, tree / 'device.mk').read_text(encoding='utf-8')
    require('TARGET_RECOVERY_DEVICE_MODULES += libn50_torch' in device and
            '$(TARGET_OUT_SHARED_LIBRARIES)/libn50_torch.so' in device, 'torch module packaging/relink rule missing')
    # Verify that the service template being patched is the one actually packaged.
    make = contained(root, root / 'bootable/recovery/etc/Android.mk').read_text(encoding='utf-8')
    match = re.search(r'LOCAL_MODULE\s*:=\s*init\.recovery\.service\.rc\b(?P<body>.*?)include\s*\$\(BUILD_PREBUILT\)', make, re.S)
    require(match is not None and 'LOCAL_SRC_FILES := init.recovery.service22.rc' in match.group('body'),
            'installed recovery service template changed')


def prepare(root, tree, verify=False):
    root, tree = root.resolve(), tree.resolve()
    validate_tree(root, tree)
    plan = []
    hashes = {}
    for relative, transform in TRANSFORMS.items():
        path = contained(root, root / relative)
        before = path.read_bytes()
        require(b'\r' not in before, 'unexpected CRLF upstream source: ' + relative)
        after = transform(before.decode('utf-8')).encode('utf-8')
        plan.append((path, before, after))
        hashes[relative] = digest(after)
    marker_path = root / MARKER
    require(not marker_path.is_symlink(), 'fix marker must not be a symlink')
    try: marker_path.resolve().relative_to(root)
    except ValueError: raise ValueError('fix marker escapes the source checkout')
    require(not marker_path.exists() or marker_path.is_file(), 'fix marker is not a regular file')
    if verify:
        require(all(before == after for _, before, after in plan), 'source fixes not applied; source build/envsetup.sh')
        marker = json.loads(contained(root, marker_path).read_text(encoding='utf-8'))
        require(marker.get('schema') == SCHEMA and marker.get('source_sha256') == hashes and
                marker.get('kernel_sha256') == KERNEL_HASHES, 'fix marker no longer matches the current source/kernel bundle')
        return
    # All contexts have passed. Only these three source files and our marker change.
    for path, before, after in plan:
        if before != after: path.write_bytes(after)
    marker = {'schema': SCHEMA, 'source_sha256': hashes, 'kernel_sha256': KERNEL_HASHES}
    marker_path.write_bytes((json.dumps(marker, indent=2) + '\n').encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--device-tree', type=Path, required=True)
    parser.add_argument('--verify', action='store_true', help='read-only build gate')
    args = parser.parse_args()
    try: prepare(args.source_root, args.device_tree, args.verify)
    except (ValueError, OSError, UnicodeError, KeyError) as error:
        print('N50_FIXES_ERROR: ' + str(error), file=sys.stderr)
        return 1
    print('N50_FIXES_OK' if args.verify else 'spaced: source fixes applied')
    return 0


if __name__ == '__main__': sys.exit(main())

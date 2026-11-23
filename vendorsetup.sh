#!/bin/bash
# Sourced by build/envsetup.sh after this tree is cloned into device/realme/spaced.
_n50_tree="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_n50_top="$(gettop)"
if ! python3 "${_n50_tree}/build/apply_fixes.py" --source-root "${_n50_top}" --device-tree "${_n50_tree}"; then
    echo "ERROR: spaced OrangeFox setup failed. BoardConfig will refuse this build." >&2
    unset _n50_tree _n50_top
    return 1
fi
unset _n50_tree _n50_top

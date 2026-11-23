# Fail closed if envsetup did not run vendorsetup.sh, or upstream source changed.
# The verifier only reads source/config; it never patches anything while make parses.
N50_SPACED_FIXES_STATUS := $(shell python3 $(DEVICE_PATH)/build/apply_fixes.py --verify --source-root . --device-tree $(DEVICE_PATH) 2>&1)
ifneq ($(strip $(N50_SPACED_FIXES_STATUS)),N50_FIXES_OK)
$(error spaced OrangeFox fixes not ready: $(N50_SPACED_FIXES_STATUS). Source build/envsetup.sh after placing this tree)
endif

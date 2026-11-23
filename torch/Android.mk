LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := libn50_torch
LOCAL_MODULE_TAGS := optional
LOCAL_MULTILIB := 64
LOCAL_SRC_FILES := torch_shim.c
LOCAL_SHARED_LIBRARIES := libc libdl
LOCAL_CFLAGS := -std=gnu11 -O2 -Wall -Wextra -Werror -fvisibility=hidden
LOCAL_LDFLAGS := -Wl,--version-script=$(LOCAL_PATH)/torch.exports.map -Wl,-z,relro,-z,now,-z,noexecstack
include $(BUILD_SHARED_LIBRARY)

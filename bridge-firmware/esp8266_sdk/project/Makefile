#############################################################
# Tuna Bridge firmware project for ESP8266 Non-OS SDK
#############################################################

TARGET = eagle
FLAVOR = release

ifndef PDIR
GEN_IMAGES = eagle.app.v6.out
GEN_BINS = eagle.app.v6.bin
SPECIAL_MKTARGETS = $(APP_MKTARGETS)
SUBDIRS = \
    user
endif

SDK_ROOT ?= /home/jens/.local/opt/esp8266/ESP8266_NONOS_SDK
APPDIR = .
LDDIR = $(SDK_ROOT)/ld

CCFLAGS += -Os

TARGET_LDFLAGS =        \
    -nostdlib           \
    -Wl,-EL             \
    --longcalls         \
    --text-section-literals

ifeq ($(FLAVOR),debug)
    TARGET_LDFLAGS += -g -O2
endif

ifeq ($(FLAVOR),release)
    TARGET_LDFLAGS += -g -O0
endif

COMPONENTS_eagle.app.v6 = \
    user/libuser.a

LINKFLAGS_eagle.app.v6 = \
    -L$(SDK_ROOT)/lib       \
    -nostdlib               \
    -T$(LD_FILE)            \
    -Wl,--no-check-sections \
    -Wl,--gc-sections       \
    -u call_user_start1     \
    -Wl,-static             \
    -Wl,--start-group       \
    -lc                     \
    -lgcc                   \
    -lhal                   \
    -lphy                   \
    -lpp                    \
    -lnet80211              \
    -llwip                  \
    -lwpa                   \
    -lcrypto                \
    -lmain                  \
    -ldriver                \
    $(DEP_LIBS_eagle.app.v6) \
    -Wl,--end-group

DEPENDS_eagle.app.v6 = \
    $(LD_FILE) \
    $(LDDIR)/eagle.rom.addr.v6.ld

CONFIGURATION_DEFINES = -DICACHE_FLASH
DEFINES += $(CONFIGURATION_DEFINES)
DDEFINES += $(CONFIGURATION_DEFINES)

INCLUDES := $(INCLUDES) -I $(PDIR)include
PDIR := $(SDK_ROOT)/
sinclude $(PDIR)Makefile

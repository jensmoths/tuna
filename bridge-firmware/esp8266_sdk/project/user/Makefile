ifndef PDIR
GEN_LIBS = libuser.a
endif

INCLUDES := $(INCLUDES) -I $(PDIR)include
INCLUDES += -I ./
INCLUDES += -I ../include
INCLUDES += -I $(SDK_ROOT)/include/ets
PDIR := ../$(PDIR)
sinclude $(PDIR)Makefile

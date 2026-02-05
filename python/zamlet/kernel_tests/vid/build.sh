#!/bin/bash
set -e

RISCV_GCC=riscv64-none-elf-gcc

RISCV_GCC_OPTS="-mcmodel=medany -static -O2 -g \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv64gcv -mabi=lp64d -std=gnu99"

INCLUDES="-I. -I../common"

RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -T../common/test.ld"

COMMON_SRCS="../common/crt.S ../common/syscalls.c"

echo "Building vid test..."
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o vid.riscv \
    vid_main.c ${COMMON_SRCS} ${RISCV_LINK_OPTS}

echo "Build successful: vid.riscv"
ls -lh vid.riscv

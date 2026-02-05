#!/bin/bash
set -e

RISCV_GCC=riscv64-none-elf-gcc

RISCV_GCC_OPTS="-mcmodel=medany -static -O2 -g \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv64gcv -mabi=lp64d -std=gnu99"

INCLUDES="-I. -I../common"

RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -T../common/test.ld"

COMMON_SRCS="../common/crt.S ../common/syscalls.c"

echo "Building bitreverse-reorder..."
SRCS="bitreverse_main.c compute_indices.c bitreverse.S bitreverse_reorder.S"
OUTPUT="bitreverse-reorder.riscv"

${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

echo "Build successful: ${OUTPUT}"
ls -lh ${OUTPUT}

echo "Building bitreverse-reorder64..."
SRCS64="bitreverse_main64.c compute_indices.c bitreverse.S bitreverse_reorder64.S"
OUTPUT64="bitreverse-reorder64.riscv"

${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT64} \
    ${SRCS64} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

echo "Build successful: ${OUTPUT64}"
ls -lh ${OUTPUT64}

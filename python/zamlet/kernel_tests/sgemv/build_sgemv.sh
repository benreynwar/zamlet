#!/bin/bash
# Build script for vec-sgemv RISC-V vector benchmark

RISCV_GCC=riscv64-none-elf-gcc

RISCV_GCC_OPTS="-DPREALLOCATE=1 -mcmodel=medany -static -O2 -g -ffast-math \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv64gcv -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I. -I../common"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -T../common/test.ld"

# Common source files
COMMON_SRCS="../common/crt.S ../common/syscalls.c ../common/ara/util.c ../common/vpu_alloc.c"

# Build small version (8x8)
echo "Building vec-sgemv (8x8)..."
SGEMV_SRCS="vec-sgemv_main.c vec-sgemv.S"
OUTPUT="vec-sgemv.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${SGEMV_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

# Build large version (16x16 = 1024 bytes, exceeds 256-byte cache)
echo ""
echo "Building vec-sgemv-large (16x16 = 1024 bytes, exceeds 256-byte cache)..."
SGEMV_SRCS="vec-sgemv-large_main.c vec-sgemv.S"
OUTPUT="vec-sgemv-large.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${SGEMV_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

# Build 64x64 version (16384 bytes)
echo ""
echo "Building vec-sgemv-64x64 (64x64 = 16384 bytes)..."
SGEMV_SRCS="vec-sgemv-64x64_main.c vec-sgemv.S"
OUTPUT="vec-sgemv-64x64.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${SGEMV_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

#!/bin/bash
# Build script for FFT RISC-V vector benchmark

RISCV_GCC=riscv64-none-elf-gcc

# Compiler options from saturn-vectors Makefile
RISCV_GCC_OPTS="-DPREALLOCATE=1 -mcmodel=medany -static -O2 -g -ffast-math \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv64gcv -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I. -I../common"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -T../common/test.ld"

# Common source files
COMMON_SRCS="../common/crt.S ../common/syscalls.c ../common/ara/util.c ../common/vpu_alloc.c"

# Build vec-fft8
echo "Building vec-fft8..."
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o vec-fft8.riscv \
    vec-fft8.c ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: vec-fft8.riscv"
    ls -lh vec-fft8.riscv
else
    echo "Build failed"
    exit 1
fi

#!/bin/bash
# Build script for vec-daxpy RISC-V vector benchmark

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

# Build vec-daxpy
echo "Building vec-daxpy..."
DAXPY_SRCS="vec-daxpy_main.c"
OUTPUT="vec-daxpy.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${DAXPY_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

# Build vec-daxpy-small
echo "Building vec-daxpy-small..."
DAXPY_SMALL_SRCS="vec-daxpy-small.c"
OUTPUT_SMALL="vec-daxpy-small.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT_SMALL} \
    ${DAXPY_SMALL_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT_SMALL}"
    ls -lh ${OUTPUT_SMALL}
else
    echo "Build failed"
    exit 1
fi

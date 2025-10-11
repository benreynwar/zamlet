#!/bin/bash
# Build script for vec-sgemv RISC-V vector benchmark

XLEN=64

# Use chipyard toolchain if available, otherwise use system toolchain
CHIPYARD_TOOLCHAIN="${HOME}/Code/chipyard/.conda-env/riscv-tools/bin"
if [ -d "$CHIPYARD_TOOLCHAIN" ]; then
    RISCV_PREFIX="${CHIPYARD_TOOLCHAIN}/riscv${XLEN}-unknown-elf-"
    echo "Using chipyard toolchain: $CHIPYARD_TOOLCHAIN"
else
    RISCV_PREFIX="riscv${XLEN}-unknown-elf-"
    echo "Using system toolchain"
fi

RISCV_GCC=${RISCV_PREFIX}gcc

# Compiler options from saturn-vectors Makefile
RISCV_GCC_OPTS="-DPREALLOCATE=1 -mcmodel=medany -static -O2 -g -ffast-math \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv${XLEN}gcv_zfh_zvfh -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I. -Icommon"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -Tcommon/test.ld"

# Source files
SGEMV_SRCS="vec-sgemv_main.c vec-sgemv.S"
COMMON_SRCS="common/crt.S common/syscalls.c common/ara/util.c"

# Output file
OUTPUT="vec-sgemv.riscv"

# Build command
echo "Building vec-sgemv..."
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${SGEMV_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

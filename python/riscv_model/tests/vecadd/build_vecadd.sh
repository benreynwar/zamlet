#!/bin/bash
# Build script for simple vector add test

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

# Compiler options
RISCV_GCC_OPTS="-mcmodel=medany -static -O2 -g \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv${XLEN}gcv -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I. -I../common"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -T../common/test.ld"

# Common source files
COMMON_SRCS="../common/crt.S ../common/syscalls.c"

# Build original vec-add (32 elements)
echo "Building vec-add (32 elements)..."
VECADD_SRCS="vec-add_main.c vec-add.S"
OUTPUT="vec-add.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${VECADD_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

# Build cache eviction test (3 x 128 elements = 1536 bytes, forces cache evictions)
echo ""
echo "Building vec-add-evict (3 arrays x 128 elements = 1536 bytes)..."
VECADD_SRCS="vec-add-evict_main.c vec-add.S"
OUTPUT="vec-add-evict.riscv"
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${VECADD_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

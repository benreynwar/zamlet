#!/bin/bash
# Build script for simple read/write byte VPU test

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

# Compiler options (simpler than sgemv)
RISCV_GCC_OPTS="-mcmodel=medany -static -O2 -g \
-fno-common -fno-builtin-printf \
-march=rv${XLEN}gc -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I../common"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lgcc -T../common/test.ld"

# Source files
TEST_SRCS="simple_vpu_test.c"
COMMON_SRCS="minimal_crt.S"

# Output file
OUTPUT="readwritebyte.riscv"

# Build command
echo "Building readwritebyte test..."
${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
    ${TEST_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

if [ $? -eq 0 ]; then
    echo "Build successful: ${OUTPUT}"
    ls -lh ${OUTPUT}
else
    echo "Build failed"
    exit 1
fi

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

# Common source files
COMMON_SRCS="minimal_crt.S"

# Test source files
TEST_FILES=(
    "simple_vpu_test.c"
    "write_then_read_many_bytes.c"
)

# Build each test
for TEST_SRC in "${TEST_FILES[@]}"; do
    # Generate output filename (replace .c with .riscv)
    OUTPUT="${TEST_SRC%.c}.riscv"

    echo "Building ${TEST_SRC}..."
    ${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
        ${TEST_SRC} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

    if [ $? -eq 0 ]; then
        echo "Build successful: ${OUTPUT}"
        ls -lh ${OUTPUT}
    else
        echo "Build failed for ${TEST_SRC}"
        exit 1
    fi
    echo ""
done

echo "All builds completed successfully"

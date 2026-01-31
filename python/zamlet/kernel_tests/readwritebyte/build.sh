#!/bin/bash
# Build script for simple read/write byte VPU test

RISCV_GCC=riscv64-none-elf-gcc

RISCV_GCC_OPTS="-mcmodel=medany -static -O2 -g \
-fno-common -fno-builtin-printf \
-march=rv64gc -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I../common"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lgcc -T../common/test.ld"

# Common source files
COMMON_SRCS="minimal_crt.S"

# Test source files
TEST_FILES=(
    "simple_vpu_test.c"
    "should_fail.c"
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

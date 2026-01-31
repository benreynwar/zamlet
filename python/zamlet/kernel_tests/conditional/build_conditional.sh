#!/bin/bash
# Build script for vec-conditional RISC-V vector benchmarks

RISCV_GCC=riscv64-none-elf-gcc

RISCV_GCC_OPTS="-DPREALLOCATE=0 -mcmodel=medany -static -O2 -g -ffast-math \
-fno-common -fno-builtin-printf -fno-tree-loop-distribute-patterns \
-march=rv64gcv -mabi=lp64d -std=gnu99"

# Include directories
INCLUDES="-I. -I../common"

# Link options
RISCV_LINK_OPTS="-static -nostdlib -nostartfiles -lm -lgcc -T../common/test.ld"

# Common source files
COMMON_SRCS="../common/crt.S ../common/syscalls.c ../common/ara/util.c ../common/vpu_alloc.c"

# Function to build a variant
build_variant() {
    local variant=$1
    local asm_file=$2
    local suffix=""
    [ -n "$variant" ] && suffix="-${variant}"

    echo "Building vec-conditional${suffix}..."
    local CONDITIONAL_SRCS="vec-conditional${suffix}_main.c ${asm_file}"
    local OUTPUT="vec-conditional${suffix}.riscv"
    ${RISCV_GCC} ${INCLUDES} ${RISCV_GCC_OPTS} -o ${OUTPUT} \
        ${CONDITIONAL_SRCS} ${COMMON_SRCS} ${RISCV_LINK_OPTS}

    if [ $? -eq 0 ]; then
        echo "Build successful: ${OUTPUT}"
        ls -lh ${OUTPUT}
    else
        echo "Build failed: ${OUTPUT}"
        exit 1
    fi
    echo ""
}

# Build all variants (if main file exists)
[ -f "vec-conditional-tiny_main.c" ] && build_variant "tiny" "vec-conditional-64.S"
[ -f "vec-conditional-small_main.c" ] && build_variant "small" "vec-conditional.S"
[ -f "vec-conditional_main.c" ] && build_variant "" "vec-conditional.S"

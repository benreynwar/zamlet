#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

void bitreverse_vec(size_t n, uint32_t* src, uint32_t* dst, int clog2_n);

static int clog2(size_t value) {
    if (value == 0) return 0;
    value = value - 1;
    int n = 0;
    while (value > 0) {
        n++;
        value = value >> 1;
    }
    return n;
}

void compute_indices(size_t n, size_t vl, uint32_t* read_idx, uint32_t* write_idx) {
    //printf("compute_indices: n=%d, vl=%d, read_idx=%p, write_idx=%p\n",
    //       (int)n, (int)vl, read_idx, write_idx);

    int clog2_n = clog2(n);
    //printf("clog2_n=%d\n", clog2_n);

    size_t vl_squared = vl * vl;
    int use_algo_a = (n >= vl_squared);
    size_t stride = n / vl;
    //printf("vl²=%d, use_algo_a=%d, stride=%d\n", (int)vl_squared, use_algo_a, (int)stride);

    asm volatile (
        "vsetvli zero, %0, e32, m1, ta, ma\n"
        "vid.v v0\n"
        :
        : "r"(vl)
    );

    uint32_t* read_ptr = read_idx;
    size_t n_cycles = n / vl;

    if (use_algo_a) {
        //printf("Using algorithm A\n");
        size_t middle_size = stride / vl;
        size_t stride_mask = stride - 1;

        asm volatile (
            "vmul.vx v8, v0, %0\n"
            :
            : "r"(stride)
        );

        for (size_t cycle = 0; cycle < n_cycles; cycle++) {
            size_t offset = cycle * vl + cycle / middle_size;
            //printf("  cycle %d: offset=%d\n", (int)cycle, (int)offset);

            asm volatile (
                "vadd.vx v1, v0, %0\n"
                "vand.vx v1, v1, %1\n"
                "vadd.vv v2, v8, v1\n"
                "vse32.v v2, (%2)\n"
                :
                : "r"(offset), "r"(stride_mask), "r"(read_ptr)
                : "memory"
            );
            read_ptr += vl;
        }
    } else {
        //printf("Using algorithm B\n");
        int log2_vl = clog2(vl);
        int log2_section_size = 2 * log2_vl - clog2_n;
        size_t section_mask = (1 << log2_section_size) - 1;
        size_t vl_mask = vl - 1;

        //printf("  log2_vl=%d, log2_section_size=%d, section_mask=%d, vl_mask=%d\n",
        //       log2_vl, log2_section_size, (int)section_mask, (int)vl_mask);

        asm volatile (
            "vsetvli zero, %0, e32, m1, ta, ma\n"
            "vsrl.vx v1, v0, %1\n"
            "vand.vx v2, v0, %2\n"
            "vmul.vx v8, v1, %0\n"
            "vmul.vx v2, v2, %3\n"
            "vadd.vv v9, v2, v1\n"
            :
            : "r"(vl), "r"(log2_section_size), "r"(section_mask), "r"(stride)
        );

        for (size_t cycle = 0; cycle < n_cycles; cycle++) {
            //printf("  cycle %d\n", (int)cycle);

            asm volatile (
                "vadd.vx v1, v9, %0\n"
                "vand.vx v1, v1, %1\n"
                "vadd.vv v2, v8, v1\n"
                "vse32.v v2, (%2)\n"
                :
                : "r"(cycle), "r"(vl_mask), "r"(read_ptr)
                : "memory"
            );
            read_ptr += vl;
        }
    }

    //printf("Calling bitreverse_vec: n=%d, src=%p, dst=%p, clog2_n=%d\n",
    //       (int)n, read_idx, write_idx, clog2_n);

    for (int i = 0; i < (int)n; i++) {
        //printf("  read_idx[%d] = %d\n", i, read_idx[i]);
    }

    bitreverse_vec(n, read_idx, write_idx, clog2_n);

    //printf("After bitreverse_vec:\n");
    for (int i = 0; i < (int)n; i++) {
        //printf("  write_idx[%d] = %d\n", i, write_idx[i]);
    }
}

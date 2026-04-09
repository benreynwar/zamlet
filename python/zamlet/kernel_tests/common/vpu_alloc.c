#include "vpu_alloc.h"
#include <stdint.h>
#include <stdlib.h>

#define VPU_BASE      0x90000000
#define VPU_POOL_SIZE (1024 * 1024)  // 1MB

#define N_LANES 4
#define WORD_WIDTH 8
#define ALIGNMENT (N_LANES * WORD_WIDTH)

static uintptr_t brk = VPU_BASE;

void* vpu_alloc(size_t size) {
    size = (size + ALIGNMENT - 1) & ~(ALIGNMENT - 1);

    brk = (brk + ALIGNMENT - 1) & ~(ALIGNMENT - 1);

    void* ptr = (void*)brk;
    brk += size;

    if (brk > VPU_BASE + VPU_POOL_SIZE) {
        exit(2);
    }

    return ptr;
}

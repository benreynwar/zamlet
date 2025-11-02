#include "vpu_alloc.h"
#include <stdint.h>
#include <stdlib.h>

#define VPU_BASE_1   0x90000000
#define VPU_BASE_8   0x90040000
#define VPU_BASE_16  0x90080000
#define VPU_BASE_32  0x900C0000
#define VPU_BASE_64  0x90100000
#define VPU_POOL_SIZE (256 * 1024)  // 256KB per pool

#define N_LANES 4
#define WORD_WIDTH 8
#define ALIGNMENT (N_LANES * WORD_WIDTH)

// Static data is now at 0x10000000, so VPU pools start at their base addresses
static uintptr_t brk_1  = VPU_BASE_1;
static uintptr_t brk_8  = VPU_BASE_8;
static uintptr_t brk_16 = VPU_BASE_16;
static uintptr_t brk_32 = VPU_BASE_32;
static uintptr_t brk_64 = VPU_BASE_64;

void* vpu_alloc(size_t size, int element_width) {
    size = (size + ALIGNMENT - 1) & ~(ALIGNMENT - 1);

    uintptr_t* brk;
    uintptr_t limit;

    switch(element_width) {
        case 1:  brk = &brk_1;  limit = VPU_BASE_1 + VPU_POOL_SIZE; break;
        case 8:  brk = &brk_8;  limit = VPU_BASE_8 + VPU_POOL_SIZE; break;
        case 16: brk = &brk_16; limit = VPU_BASE_16 + VPU_POOL_SIZE; break;
        case 32: brk = &brk_32; limit = VPU_BASE_32 + VPU_POOL_SIZE; break;
        case 64: brk = &brk_64; limit = VPU_BASE_64 + VPU_POOL_SIZE; break;
        default:
            exit(1);
    }

    // Align the current brk pointer before using it
    *brk = (*brk + ALIGNMENT - 1) & ~(ALIGNMENT - 1);

    void* ptr = (void*)*brk;
    *brk += size;

    if (*brk > limit) {
        exit(2);
    }

    return ptr;
}

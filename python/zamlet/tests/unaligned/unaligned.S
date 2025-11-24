    .text
    .balign 4
    .global vec_load_store_unaligned
# RV64V system
#
# void vec_load_store_unaligned(size_t n, const uint8_t* src, size_t src_byte_off,
#                                uint8_t* dst, size_t dst_byte_off)
#
# Loads n 64-bit elements from src+src_byte_off, stores to dst+dst_byte_off
# Byte offsets can be any value - truly unaligned accesses

#define n a0
#define srcp a1
#define src_byte_off a2
#define dstp a3
#define dst_byte_off a4

vec_load_store_unaligned:
    # Check for zero size
    beqz n, exit

    # Calculate actual source address: srcp + src_byte_off
    add srcp, srcp, src_byte_off

    # Calculate actual destination address: dstp + dst_byte_off
    add dstp, dstp, dst_byte_off

loop:
    # Set vector length for 64-bit integers
    vsetvli t0, n, e64, m8, ta, ma

    # Load vector from source (unaligned)
    vle64.v v0, (srcp)

    # Store vector to destination (unaligned)
    vse64.v v0, (dstp)

    # Calculate byte offset (t0 elements * 8 bytes each)
    slli t1, t0, 3

    # Advance pointers
    add srcp, srcp, t1
    add dstp, dstp, t1

    # Decrement count and loop if more elements
    sub n, n, t0
    bnez n, loop

exit:
    ret

    .text
    .balign 4
    .global vec_add_scalar
# RV64V system
#
# void vec_add_scalar(size_t n, const int32_t* src, int32_t* dst, int32_t scalar)
#
# Adds scalar to each element of src array and stores in dst
# src and dst can be the same array for in-place operation

#define n a0
#define srcp a1
#define dstp a2
#define scalar a3

vec_add_scalar:
    # Check for zero size
    beqz n, exit

loop:
    # Set vector length for 32-bit integers
    vsetvli t0, n, e32, m1, ta, ma

    # Load vector from source
    vle32.v v0, (srcp)

    # Add scalar to all elements
    vadd.vx v0, v0, scalar

    # Store result to destination
    vse32.v v0, (dstp)

    # Calculate byte offset (t0 elements * 4 bytes each)
    slli t1, t0, 2

    # Advance pointers
    add srcp, srcp, t1
    add dstp, dstp, t1

    # Decrement count and loop if more elements
    sub n, n, t0
    bnez n, loop

exit:
    ret

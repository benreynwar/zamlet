    .text
    .balign 4
    .global vec_sgemv
# RV64IDV system
#
# void
# vec_sgemv(size_t m,
#          size_t n,
#          const float* v,   // m-length vector
#          const float* m,   // m * n matrix
#          float*c)          // m-length vector
#
#  c += a*b (V^T * M)
#  matrix stored in row-major order

#define m a0
#define n a1
#define vp a2
#define mp a3
#define cp a4

#define vt t1
#define mpm t2
#define nvl t3
#define nstride t4
#define mt t5
#define nvlb t6


vec_sgemv:
    # Check for zero size matrices - early exit if either dimension is 0
    beqz m, exit
    beqz n, exit

    # Convert element stride to byte stride for matrix rows
    # nstride = n * 4 bytes (since each float is 4 bytes)
    # This is used to advance to the next row of the matrix
    slli nstride, n, 2

    # Check if matrix pointer is valid (appears to check for minimum alignment/value)
    slti mt, mp, 2
    bnez mt, exit

c_col_loop:
    # Set vector length for processing n elements at a time
    # e32 = 32-bit elements (floats), m8 = LMUL of 8 (use 8 vector registers)
    # ta = tail agnostic, ma = mask agnostic
    # nvl = actual number of elements that will be processed (may be less than n)
    vsetvli nvl, n, e32, m8, ta, ma # 32-bit vectors, LMUL=8

    mv mt, m   # mt = row counter, initialize to m (number of rows)
    mv vt, vp  # vt = pointer to current element in vector v

    # Load current partial result vector from output array c
    # This will be accumulated with V^T * M
    vle32.v v16, (cp)

    # Prefetch first two rows of matrix M into vector registers
    # v0 = first row of M (nvl elements starting at current column)
    vle32.v v0, (mp)
    add mpm, mp, nstride  # mpm points to second row
    vle32.v v8, (mpm)     # v8 = second row of M
    add mpm, mpm, nstride # mpm points to third row

    # Prefetch first two elements of vector v into scalar registers
    flw ft0, (vp)    # ft0 = v[0]
    flw ft1, 4(vp)   # ft1 = v[1]
    addi vt, vp, 8   # vt points to v[2]

m_loop:
    # Main loop: processes 2 rows of M per iteration (software pipelining for efficiency)
    # Computes: v16 += v[i] * M[i,:] for each row i

    vfmacc.vf v16, ft0, v0      # v16 += ft0 * v0 (accumulate first row: c += v[i] * M[i,:])
    vle32.v v0, (mpm)           # Prefetch next row of M into v0 (for iteration i+2)
    flw ft0, (vt)               # Prefetch next scalar from v into ft0 (v[i+2])
    add mpm, mpm, nstride       # Advance matrix pointer to row i+3
    addi mt, mt, -2             # Decrement row counter by 2 (processing 2 rows per loop)
    vfmacc.vf v16, ft1, v8      # v16 += ft1 * v8 (accumulate second row: c += v[i+1] * M[i+1,:])
    vle32.v v8, (mpm)           # Prefetch next row of M into v8 (for iteration i+3)
    add mpm, mpm, nstride       # Advance matrix pointer to row i+4
    flw ft1, 4(vt)              # Prefetch next scalar from v into ft1 (v[i+3])
    addi vt, vt, 8              # Advance vector pointer by 2 floats (8 bytes)
    slti t0, mt, 4              # Check if fewer than 4 rows remain
    bnez t0, 1f                 # If so, exit main loop and handle remainder
    j m_loop                    # Otherwise continue main loop

1:  # Cleanup: process the remaining prefetched rows (2 or 3 rows left)
    vfmacc.vf v16, ft0, v0      # Process row i+2
    addi mt, mt, -2             # Decrement by 2
    vfmacc.vf v16, ft1, v8      # Process row i+3

    beqz mt, 1f                 # If no rows remain, skip to store

    # If 1 odd row remains, process it
    vle32.v v0, (mpm)           # Load the last row
    flw ft0, (vt)               # Load the last scalar from v
    vfmacc.vf v16, ft0, v0      # v16 += v[m-1] * M[m-1,:]

1:  # Store the accumulated result for this chunk of columns
    vse32.v v16, (cp)           # Write v16 back to output vector c

    # Advance pointers to process next chunk of columns (strip mining)
    slli nvlb, nvl, 2           # Convert nvl (elements) to bytes (nvl * 4)
    add cp, cp, nvlb            # Advance output pointer by nvl elements
    add mp, mp, nvlb            # Advance matrix pointer to next set of columns

    sub n, n, nvl               # Decrement remaining columns to process
    bnez n, c_col_loop          # If columns remain, continue outer loop

exit:
    ret

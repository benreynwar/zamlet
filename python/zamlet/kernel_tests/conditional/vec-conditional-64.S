  .text
  .balign 4
  .global vec_conditional

# (int64) z[i] = ((int64) x[i] < 5) ? (int64) a[i] : (int64) b[i];
#
vec_conditional:
  vsetvli t0, a0, e64, m1, ta, ma # Use 64b elements.
  vle64.v v0, (a1)         # Get x[i]
    sub a0, a0, t0        # Decrement element count
    slli t1, t0, 3        # Multiply by 8 bytes
    add a1, a1, t1        # x[i] Bump pointer
  vmslt.vi v0, v0, 5      # Set mask in v0
  vle64.v v2, (a2), v0.t  # z[i] = a[i] case
  vmnot.m v0, v0          # Invert v0
    add a2, a2, t1        # a[i] bump pointer
  vle64.v v2, (a3), v0.t  # z[i] = b[i] case
    add a3, a3, t1        # b[i] bump pointer
  vse64.v v2, (a4)        # Store z
    add a4, a4, t1        # z[i] bump pointer
    bnez a0, vec_conditional # Any more?
    ret


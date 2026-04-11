#ifndef ZAMLET_CUSTOM_H
#define ZAMLET_CUSTOM_H

/*
 * Wrappers for zamlet custom-0 opcode (0x0b) instructions.
 *
 * Three instructions, distinguished by funct3:
 *   funct3=0  set_index_bound   bound indexed-access offsets to lower N bits
 *   funct3=1  begin_writeset    open a shared writeset scope
 *   funct3=2  end_writeset      close the writeset scope
 *
 * See python/zamlet/instructions/custom.py for semantics.
 */

/*
 * Bound subsequent indexed load/store byte offsets to the lower `bits` bits,
 * so the address range is [base, base + (1 << bits)). Lets the lamlet pre-check
 * all pages in that range and skip per-element fault detection.
 *
 * Passing 0 disables the bound.
 *
 * Always emits the register form of the instruction (rs1 != x0 holding `bits`,
 * or rs1 == x0 when the compiler picks that, both of which the core decodes
 * correctly per custom.py: rs1==x0 uses imm=0, rs1!=x0 reads x[rs1]).
 */
static inline void zamlet_set_index_bound(unsigned bits) {
    asm volatile(".insn i 0x0b, 0, x0, %0, 0" : : "r"(bits));
}

/*
 * Open a writeset scope. Vector operations within the scope share a
 * writeset_ident and bypass each other in the cache table — use this to mark
 * a group of scatters that are known not to collide (e.g., a permutation).
 */
static inline void zamlet_begin_writeset(void) {
    asm volatile(".insn i 0x0b, 1, x0, x0, 0");
}

/*
 * Close the writeset scope opened by zamlet_begin_writeset.
 */
static inline void zamlet_end_writeset(void) {
    asm volatile(".insn i 0x0b, 2, x0, x0, 0");
}

#endif /* ZAMLET_CUSTOM_H */

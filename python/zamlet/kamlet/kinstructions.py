'''
Opcode = 6 bit

registers can point at the register file, or at received messages

Load             dst (6 bit)    sram (12 bit)  mask (5 bit)  length (3) sp_or_mem (1) = 33 bit  if mem it needs an address too
Store            src (6 bit)    sram (12 bit)  mask (5 bit)  length (3) sp_or_mem (1) = 33 bit  if mem it needs an address too
Read Line        sram (12 bit)  memory (64 memory) length (3)  = 21 + 64 bit
Write Line       sram (12 bit)  memory (64 memory) length (3)  = 21 + 64 bit   + 1 bit for if evicting
Operation        dst (6 bit) src1 (6 bit) src2 (6 bit)  mask (5 bit) (length 3) = 24 bit
Send             src (6 bit)    target (6 bit) mask (5 bit)  length (3)  =  26 bit
'''

import logging
import struct
from dataclasses import dataclass
from enum import Enum, IntEnum

from zamlet import addresses
from zamlet.addresses import KMAddr, GlobalAddress
from zamlet.params import ZamletParams
from zamlet.control_structures import pack_fields_to_int
from zamlet.message import IdentHeader, MessageType, SendType
from zamlet.monitor import CompletionType, SpanType


logger = logging.getLogger(__name__)


class VArithOp(Enum):
    # Integer
    ADD = "add"
    SUB = "sub"
    RSUB = "rsub"
    MUL = "mul"
    MACC = "macc"
    MADD = "madd"
    NMSAC = "nmsac"
    NMSUB = "nmsub"
    AND = "and"
    OR = "or"
    XOR = "xor"
    SLL = "sll"
    SRL = "srl"
    SRA = "sra"
    MIN = "min"
    MAX = "max"
    MINU = "minu"
    MAXU = "maxu"
    # Float
    FADD = "fadd"
    FSUB = "fsub"
    FMUL = "fmul"
    FDIV = "fdiv"
    FMACC = "fmacc"
    FNMACC = "fnmacc"
    FMADD = "fmadd"
    FNMADD = "fnmadd"
    FMSAC = "fmsac"
    FNMSAC = "fnmsac"
    FMSUB = "fmsub"
    FNMSUB = "fnmsub"
    FRSUB = "frsub"
    FRDIV = "frdiv"
    FMIN = "fmin"
    FMAX = "fmax"


class VUnaryOp(Enum):
    COPY = "copy"
    SEXT = "sext"
    ZEXT = "zext"
    NSRL = "nsrl"
    FCVT_XU_F = "xu.f"
    FCVT_X_F = "x.f"
    FCVT_F_XU = "f.xu"
    FCVT_F_X = "f.x"
    FCVT_RTZ_XU_F = "rtz.xu.f"
    FCVT_RTZ_X_F = "rtz.x.f"


class VCmpOp(Enum):
    EQ = "seq"
    NE = "sne"
    LTU = "sltu"
    LT = "slt"
    LEU = "sleu"
    LE = "sle"
    GTU = "sgtu"
    GT = "sgt"


class VRedOp(Enum):
    # Single-width integer
    SUM = "sum"
    MAXU = "maxu"
    MAX = "max"
    MINU = "minu"
    MIN = "min"
    AND = "and"
    OR = "or"
    XOR = "xor"
    # Single-width float (excluding ordered)
    FSUM = "fsum"
    FMAX = "fmax"
    FMIN = "fmin"
    # Widening integer
    WSUMU = "wsumu"
    WSUM = "wsum"
    # Widening float (excluding ordered)
    FWSUM = "fwsum"


class KInstr:
    @property
    def finalize_after_send(self) -> bool:
        """Whether to finalize children after sending the instruction to kamlets.

        Override to return False if additional children (like response messages)
        will be added later.
        """
        return True

    def create_span(self, monitor, parent_span_id: int) -> int:
        """Create a span for this kinstr."""
        return monitor.create_span(
            span_type=SpanType.KINSTR,
            component="lamlet",
            completion_type=CompletionType.FIRE_AND_FORGET,
            parent_span_id=parent_span_id,
            instr_type=type(self).__name__,
            instr_ident=self.instr_ident,
        )


class TrackedKInstr(KInstr):
    """KInstr subclass for instructions where lamlet waits for a response."""
    def create_span(self, monitor, parent_span_id: int) -> int:
        return monitor.create_span(
            span_type=SpanType.KINSTR,
            component="lamlet",
            completion_type=CompletionType.TRACKED,
            parent_span_id=parent_span_id,
            instr_type=type(self).__name__,
            instr_ident=self.instr_ident,
        )


class KInstrOpcode(IntEnum):
    SYNC_TRIGGER = 0
    IDENT_QUERY = 1
    LOAD_J2J = 2
    STORE_J2J = 3
    LOAD_SIMPLE = 4
    STORE_SIMPLE = 5
    LOAD_IMM = 6
    WRITE_PARAM = 7
    STORE_SCALAR = 8


KINSTR_WIDTH = 64
OPCODE_WIDTH = 6
SYNC_IDENT_WIDTH = 8
SYNC_VALUE_WIDTH = 8


@dataclass
class SyncTrigger(KInstr):
    """Trigger a sync event on the sync network.

    Matches Chisel SyncTriggerInstr layout:
      opcode(6), syncIdent(8), value(8), reserved(42)
    """
    opcode: int = KInstrOpcode.SYNC_TRIGGER
    sync_ident: int = 0
    value: int = 0

    FIELD_SPECS = [
        ('opcode', OPCODE_WIDTH),
        ('sync_ident', SYNC_IDENT_WIDTH),
        ('value', SYNC_VALUE_WIDTH),
        ('_padding', KINSTR_WIDTH - OPCODE_WIDTH - SYNC_IDENT_WIDTH - SYNC_VALUE_WIDTH),
    ]

    def encode(self) -> int:
        return pack_fields_to_int(self, self.FIELD_SPECS)


@dataclass
class SetIndexBound(KInstr):
    """Set kamlet-level index bound for indexed load/store masking.

    0 = no bound (full 64-bit indices), N = mask indices to lower N bits.
    """
    # 0 = no bound, N = mask to lower N bits
    index_bound_bits: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        kamlet.index_bound_bits = self.index_bound_bits
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class FreeRegister(KInstr):
    """Release the rename-table entry for an architectural register.

    The kamlet returns the physical register currently mapped to this
    architectural register to its free queue and marks the architectural
    register unmapped. Subsequent reads of this register before the next
    write fail the rename-table validity assert.

    Primary use: the lamlet emits this at the end of every compound op for
    each scratch register it used. May also be used in the future to free
    other architectural registers whose values are known-dead.
    """
    reg: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        kamlet.rename_table.free_register(self.reg)
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class LoadImmByte(KInstr):
    """
    This instruction writes an immediate to a byte of a vector register.
    """
    dst: addresses.RegAddr
    imm: int
    # Which bits of the byte we write.
    bit_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    # Offset of the mask in the mask register (in multiples of j_in_l)
    # Needed since we may be writing into the middle of a vector group.
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_imm_byte_instr(self)


@dataclass
class LoadWord(KInstr):
    """
    This instruction load a word from memory to a location in a vector register.
    """
    dst: addresses.RegAddr
    src: KMAddr
    # Which bytes to the word we write
    byte_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_word_instr(self)


@dataclass
class LoadImmWord(KInstr):
    """
    This instruction writes an immediate to a byte of a vector register.
    """
    dst: addresses.RegAddr
    imm: bytes
    # Which bytes of the word we write
    byte_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_imm_word_instr(self)

@dataclass
class StoreScalar(KInstr):
    """
    Stores data from a vector register to scalar memory.
    The kamlet reads the register, then sends a WRITE_MEM_WORD_REQ to the lamlet.

    In bit_mode: writes n_bytes_or_bits bits starting at dst_bit_in_byte within dst_byte_in_word.
    Otherwise: writes n_bytes_or_bits contiguous bytes starting at dst_byte_in_word.
    """
    src: addresses.RegAddr
    scalar_addr: int
    dst_byte_in_word: int
    n_bytes_or_bits: int
    bit_mode: bool
    dst_bit_in_byte: int
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_store_scalar_instr(self)


@dataclass
class StoreWord(KInstr):
    """
    This instruction stores a word from a vector register to memory.
    """
    src: addresses.RegAddr
    dst: KMAddr
    # Which bytes of the word we write
    byte_mask: int
    # An identifier. Writes with the same writeset_ident are guaranteed not to clash.
    writeset_ident: int
    mask_reg: int
    mask_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_store_word_instr(self)


@dataclass
class Load(KInstr):
    """
    A load from the VPU memory into a vector register.
    The k_maddr points to the location of the start_index element.

    stride_bytes: byte stride between elements. None = unit stride (ew/8 bytes).
    """
    dst: int
    # The address of the start_index element in the kamlet address space.
    k_maddr: KMAddr
    start_index: int
    n_elements: int
    dst_ordering: addresses.Ordering  # src ordering is held in k_maddr
    mask_reg: int|None
    writeset_ident: int
    instr_ident: int
    stride_bytes: int|None = None

    async def update_kamlet(self, kamlet):
        await kamlet.handle_load_instr(self)


@dataclass
class Store(KInstr):
    """
    A store from a vector register to VPU memory.

    stride_bytes: byte stride between elements. None = unit stride (ew/8 bytes).
    """
    src: int
    k_maddr: KMAddr  # An address in the kamlet address space
    start_index: int
    n_elements: int
    src_ordering: addresses.Ordering
    mask_reg: int
    writeset_ident: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_store_instr(self)


def _vcmp_evaluate(op: VCmpOp, a, b):
    """Evaluate a vector comparison operation. Returns 1 or 0."""
    if op == VCmpOp.EQ:
        return 1 if a == b else 0
    elif op == VCmpOp.NE:
        return 1 if a != b else 0
    elif op == VCmpOp.LE:
        return 1 if a <= b else 0
    elif op == VCmpOp.LT:
        return 1 if a < b else 0
    elif op == VCmpOp.GT:
        return 1 if a > b else 0
    elif op == VCmpOp.GTU:
        return 1 if a > b else 0
    elif op == VCmpOp.LEU:
        return 1 if a <= b else 0
    elif op == VCmpOp.LTU:
        return 1 if a < b else 0
    else:
        raise NotImplementedError(f"Unknown comparison op: {op}")


@dataclass
class VCmpViOp(KInstr):
    op: VCmpOp
    dst: int
    src: int
    simm5: int
    n_elements: int
    element_width: int
    ordering: addresses.Ordering
    instr_ident: int

    async def update_kamlet(self, kamlet):
        wb = kamlet.params.word_bytes
        bits_per_jamlet_vline = wb * 8
        vline_bytes = kamlet.params.vline_bytes
        n_src_vlines = (self.n_elements * self.element_width + vline_bytes * 8 - 1) // (
            vline_bytes * 8)
        n_dst_vlines = (self.n_elements + vline_bytes * 8 - 1) // (vline_bytes * 8)
        # Mask result has 1 bit per element.
        dst_elements_in_vline = vline_bytes * 8

        # Rename: lookup src physes before allocating dst physes.
        src_pregs = [kamlet.r(self.src + i) for i in range(n_src_vlines)]
        dst_pregs = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline, mask_present=False)

        await kamlet.wait_for_rf_available(
            read_regs=src_pregs, write_regs=dst_pregs, instr_ident=self.instr_ident,
        )
        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)
        eb = self.element_width // 8

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index // kamlet.params.j_in_l
            if k_index != kamlet.k_index:
                continue
            jamlet = kamlet.jamlets[j_in_k_index]

            src_bit_in_jvec = element_in_jamlet * self.element_width
            src_vline_idx = src_bit_in_jvec // bits_per_jamlet_vline
            src_byte_in_vline = (src_bit_in_jvec % bits_per_jamlet_vline) // 8
            assert (src_bit_in_jvec % bits_per_jamlet_vline) % 8 == 0
            src_base = src_pregs[src_vline_idx] * wb
            src_bytes = jamlet.rf_slice[src_base + src_byte_in_vline:
                                        src_base + src_byte_in_vline + eb]
            src_val = int.from_bytes(src_bytes, byteorder='little', signed=not unsigned)
            result_bit = _vcmp_evaluate(self.op, src_val, sign_extended_imm)

            dst_bit_in_jvec = element_in_jamlet
            dst_vline_idx = dst_bit_in_jvec // bits_per_jamlet_vline
            dst_bit_in_vline = dst_bit_in_jvec % bits_per_jamlet_vline
            dst_byte_in_vline = dst_bit_in_vline // 8
            dst_bit_offset = dst_bit_in_vline % 8
            dst_base = dst_pregs[dst_vline_idx] * wb
            if result_bit:
                jamlet.rf_slice[dst_base + dst_byte_in_vline] |= (1 << dst_bit_offset)
            else:
                jamlet.rf_slice[dst_base + dst_byte_in_vline] &= ~(1 << dst_bit_offset)

        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VCmpVxOp(KInstr):
    op: VCmpOp
    dst: int
    src: int
    scalar_bytes: bytes
    n_elements: int
    element_width: int
    ordering: addresses.Ordering
    instr_ident: int

    async def update_kamlet(self, kamlet):
        wb = kamlet.params.word_bytes
        bits_per_jamlet_vline = wb * 8
        vline_bytes = kamlet.params.vline_bytes
        n_src_vlines = (self.n_elements * self.element_width + vline_bytes * 8 - 1) // (
            vline_bytes * 8)
        n_dst_vlines = (self.n_elements + vline_bytes * 8 - 1) // (vline_bytes * 8)
        dst_elements_in_vline = vline_bytes * 8

        # Rename: lookup src physes before allocating dst physes.
        src_pregs = [kamlet.r(self.src + i) for i in range(n_src_vlines)]
        dst_pregs = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline, mask_present=False)

        await kamlet.wait_for_rf_available(
            read_regs=src_pregs, write_regs=dst_pregs, instr_ident=self.instr_ident,
        )
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)
        eb = self.element_width // 8
        scalar_val = int.from_bytes(
            self.scalar_bytes[:eb], byteorder='little', signed=not unsigned,
        )

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index // kamlet.params.j_in_l
            if k_index != kamlet.k_index:
                continue
            jamlet = kamlet.jamlets[j_in_k_index]

            src_bit_in_jvec = element_in_jamlet * self.element_width
            src_vline_idx = src_bit_in_jvec // bits_per_jamlet_vline
            src_byte_in_vline = (src_bit_in_jvec % bits_per_jamlet_vline) // 8
            assert (src_bit_in_jvec % bits_per_jamlet_vline) % 8 == 0
            src_base = src_pregs[src_vline_idx] * wb
            src_bytes = jamlet.rf_slice[src_base + src_byte_in_vline:
                                        src_base + src_byte_in_vline + eb]
            src_val = int.from_bytes(src_bytes, byteorder='little', signed=not unsigned)
            result_bit = _vcmp_evaluate(self.op, src_val, scalar_val)

            dst_bit_in_jvec = element_in_jamlet
            dst_vline_idx = dst_bit_in_jvec // bits_per_jamlet_vline
            dst_bit_in_vline = dst_bit_in_jvec % bits_per_jamlet_vline
            dst_byte_in_vline = dst_bit_in_vline // 8
            dst_bit_offset = dst_bit_in_vline % 8
            dst_base = dst_pregs[dst_vline_idx] * wb
            if result_bit:
                jamlet.rf_slice[dst_base + dst_byte_in_vline] |= (1 << dst_bit_offset)
            else:
                jamlet.rf_slice[dst_base + dst_byte_in_vline] &= ~(1 << dst_bit_offset)

        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VCmpVvOp(KInstr):
    op: VCmpOp
    dst: int
    src1: int
    src2: int
    n_elements: int
    element_width: int
    ordering: addresses.Ordering
    instr_ident: int

    async def update_kamlet(self, kamlet):
        wb = kamlet.params.word_bytes
        bits_per_jamlet_vline = wb * 8
        vline_bytes = kamlet.params.vline_bytes
        n_src_vlines = (self.n_elements * self.element_width + vline_bytes * 8 - 1) // (
            vline_bytes * 8)
        n_dst_vlines = (self.n_elements + vline_bytes * 8 - 1) // (vline_bytes * 8)
        dst_elements_in_vline = vline_bytes * 8

        # Rename: lookup src physes before allocating dst physes.
        src1_pregs = [kamlet.r(self.src1 + i) for i in range(n_src_vlines)]
        src2_pregs = [kamlet.r(self.src2 + i) for i in range(n_src_vlines)]
        dst_pregs = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline, mask_present=False)

        read_regs = list(src1_pregs) + list(src2_pregs)
        await kamlet.wait_for_rf_available(
            read_regs=read_regs, write_regs=dst_pregs, instr_ident=self.instr_ident,
        )
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)
        eb = self.element_width // 8

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index // kamlet.params.j_in_l
            if k_index != kamlet.k_index:
                continue
            jamlet = kamlet.jamlets[j_in_k_index]

            src_bit_in_jvec = element_in_jamlet * self.element_width
            src_vline_idx = src_bit_in_jvec // bits_per_jamlet_vline
            src_byte_in_vline = (src_bit_in_jvec % bits_per_jamlet_vline) // 8
            assert (src_bit_in_jvec % bits_per_jamlet_vline) % 8 == 0
            s1_off = src1_pregs[src_vline_idx] * wb + src_byte_in_vline
            s2_off = src2_pregs[src_vline_idx] * wb + src_byte_in_vline
            src1_bytes = jamlet.rf_slice[s1_off:s1_off + eb]
            src2_bytes = jamlet.rf_slice[s2_off:s2_off + eb]
            src1_val = int.from_bytes(src1_bytes, byteorder='little', signed=not unsigned)
            src2_val = int.from_bytes(src2_bytes, byteorder='little', signed=not unsigned)
            result_bit = _vcmp_evaluate(self.op, src2_val, src1_val)

            dst_bit_in_jvec = element_in_jamlet
            dst_vline_idx = dst_bit_in_jvec // bits_per_jamlet_vline
            dst_bit_in_vline = dst_bit_in_jvec % bits_per_jamlet_vline
            dst_byte_in_vline = dst_bit_in_vline // 8
            dst_bit_offset = dst_bit_in_vline % 8
            dst_base = dst_pregs[dst_vline_idx] * wb
            if result_bit:
                jamlet.rf_slice[dst_base + dst_byte_in_vline] |= (1 << dst_bit_offset)
            else:
                jamlet.rf_slice[dst_base + dst_byte_in_vline] &= ~(1 << dst_bit_offset)

        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VmnandMmOp(KInstr):
    dst: int
    src1: int
    src2: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        # Rename: lookup src physes before allocating dst phys.
        src1_preg = kamlet.r(self.src1)
        src2_preg = kamlet.r(self.src2)
        dst_preg = kamlet.w(self.dst)

        # src1/src2 may alias (same arch -> same phys); duplicates in read_regs
        # are harmless because wait_for_rf_available only stalls, no locking.
        read_regs = [src1_preg]
        if src2_preg != src1_preg:
            read_regs.append(src2_preg)
        await kamlet.wait_for_rf_available(read_regs=read_regs, write_regs=[dst_preg],
                                           instr_ident=self.instr_ident)

        wb = kamlet.params.word_bytes
        src1_base = src1_preg * wb
        src2_base = src2_preg * wb
        dst_base = dst_preg * wb
        for jamlet in kamlet.jamlets:
            for byte_offset in range(wb):
                src1_byte = jamlet.rf_slice[src1_base + byte_offset]
                src2_byte = jamlet.rf_slice[src2_base + byte_offset]
                result_byte = ~(src1_byte & src2_byte) & 0xff
                jamlet.rf_slice[dst_base + byte_offset] = result_byte
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VBroadcastOp(KInstr):
    """Broadcast a scalar value to all elements of a vector register.

    Used for vmv.v.i, vmv.v.x, vmerge instructions.
    """
    dst: int
    scalar: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int
    mask_reg: int | None = None

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        elements_in_vline = bits_in_vline // self.element_width

        # Rename: lookup mask phys before allocating dst phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_pregs = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline,
            mask_present=self.mask_reg is not None)

        await kamlet.wait_for_rf_available(write_regs=dst_pregs, instr_ident=self.instr_ident)

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                dst_base = dst_pregs[vline_index] * wb
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width,
                        self.word_order, mask_preg,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        result_bytes = self.scalar.to_bytes(
                            eb, byteorder='little', signed=(self.scalar < 0))
                        jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb] = result_bytes
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VidOp(KInstr):
    """Write element indices to a vector register.

    Used for vid.v instruction: vd[i] = i
    """
    dst: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    mask_reg: int | None
    instr_ident: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        elements_in_vline = bits_in_vline // self.element_width

        # Rename: lookup mask phys before allocating dst phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_pregs = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline,
            mask_present=self.mask_reg is not None)

        await kamlet.wait_for_rf_available(write_regs=dst_pregs, instr_ident=self.instr_ident)

        params = kamlet.params
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0
        elements_in_vline = params.vline_bytes * 8 // self.element_width

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            vw_index = addresses.k_indices_to_vw_index(
                params, self.word_order, kamlet.k_index, j_in_k_index)
            for vline_index in range(n_vlines):
                dst_base = dst_pregs[vline_index] * wb
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    element_index = (vline_index * elements_in_vline +
                                     index_in_j * params.j_in_l + vw_index)
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        mask_preg, vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        result_bytes = element_index.to_bytes(eb, byteorder='little', signed=False)
                        jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb] = (
                            result_bytes
                        )
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VUnaryOvOp(KInstr):
    """Unary vector operation. Source and destination may have different element widths."""
    op: VUnaryOp
    dst: int
    src: int
    n_elements: int
    dst_ew: int
    src_ew: int
    word_order: addresses.WordOrder
    mask_reg: int | None
    instr_ident: int
    shift_amount: int = 0  # For NSRL: 5-bit uimm, masked to lg2(2*SEW) bits at compute time

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        n_src_vlines = (self.n_elements * self.src_ew + bits_in_vline - 1) // bits_in_vline
        dst_elements_in_vline = bits_in_vline // self.dst_ew

        # Rename: lookup src physes (and mask) before allocating dst physes.
        src_pregs = [kamlet.r(self.src + i) for i in range(n_src_vlines)]
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_pregs = kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline,
            mask_present=self.mask_reg is not None)

        await kamlet.wait_for_rf_available(
            read_regs=src_pregs, write_regs=dst_pregs, instr_ident=self.instr_ident)

        params = kamlet.params
        src_eb = self.src_ew // 8
        dst_eb = self.dst_ew // 8
        wb = params.word_bytes

        dst_elements_per_word = wb // dst_eb
        src_elements_per_word = wb // src_eb
        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_dst_vlines):
                dst_base = dst_pregs[vline_index] * wb
                for index_in_j in range(dst_elements_per_word):
                    valid_element, mask_bit = kamlet.get_is_active(
                        0, self.n_elements, self.dst_ew, self.word_order,
                        mask_preg, vline_index, j_in_k_index, index_in_j)
                    if not (valid_element and mask_bit):
                        continue
                    # Element index within this jamlet
                    dst_elem = vline_index * dst_elements_per_word + index_in_j
                    # Same element in the source layout
                    src_vline = dst_elem // src_elements_per_word
                    src_idx = dst_elem % src_elements_per_word
                    src_base = src_pregs[src_vline] * wb
                    dst_byte = dst_base + index_in_j * dst_eb
                    src_byte = src_base + src_idx * src_eb
                    src_bytes = jamlet.rf_slice[src_byte:src_byte + src_eb]
                    result = self._convert(src_bytes, src_eb, dst_eb)
                    jamlet.rf_slice[dst_byte:dst_byte + dst_eb] = result
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)

    def _convert(self, src_bytes: bytes, src_eb: int, dst_eb: int) -> bytes:
        if self.op == VUnaryOp.COPY:
            assert src_eb == dst_eb
            return src_bytes
        elif self.op == VUnaryOp.ZEXT:
            return src_bytes + b'\x00' * (dst_eb - src_eb)
        elif self.op == VUnaryOp.SEXT:
            sign_bit = src_bytes[-1] & 0x80
            pad = b'\xff' if sign_bit else b'\x00'
            return src_bytes + pad * (dst_eb - src_eb)
        elif self.op == VUnaryOp.NSRL:
            src_val = int.from_bytes(src_bytes, byteorder='little', signed=False)
            shift_mask = src_eb * 8 * 2 - 1  # low lg2(2*SEW) bits
            shifted = src_val >> (self.shift_amount & shift_mask)
            return (shifted & ((1 << (dst_eb * 8)) - 1)).to_bytes(
                dst_eb, byteorder='little')
        elif self.op in (VUnaryOp.FCVT_XU_F, VUnaryOp.FCVT_RTZ_XU_F):
            assert src_eb == dst_eb
            float_fmt = {8: 'd', 4: 'f'}[src_eb]
            uint_fmt = {8: '<Q', 4: '<I'}[dst_eb]
            max_uint = (1 << (dst_eb * 8)) - 1
            float_val = struct.unpack(float_fmt, src_bytes)[0]
            int_val = max(0, min(int(float_val), max_uint))
            return struct.pack(uint_fmt, int_val)
        elif self.op in (VUnaryOp.FCVT_X_F, VUnaryOp.FCVT_RTZ_X_F):
            assert src_eb == dst_eb
            float_fmt = {8: 'd', 4: 'f'}[src_eb]
            sint_fmt = {8: '<q', 4: '<i'}[dst_eb]
            max_sint = (1 << (dst_eb * 8 - 1)) - 1
            min_sint = -(1 << (dst_eb * 8 - 1))
            float_val = struct.unpack(float_fmt, src_bytes)[0]
            int_val = max(min_sint, min(int(float_val), max_sint))
            return struct.pack(sint_fmt, int_val)
        elif self.op == VUnaryOp.FCVT_F_XU:
            assert src_eb == dst_eb
            uint_fmt = {8: '<Q', 4: '<I'}[src_eb]
            float_fmt = {8: 'd', 4: 'f'}[dst_eb]
            uint_val = struct.unpack(uint_fmt, src_bytes)[0]
            return struct.pack(float_fmt, float(uint_val))
        elif self.op == VUnaryOp.FCVT_F_X:
            assert src_eb == dst_eb
            sint_fmt = {8: '<q', 4: '<i'}[src_eb]
            float_fmt = {8: 'd', 4: 'f'}[dst_eb]
            sint_val = struct.unpack(sint_fmt, src_bytes)[0]
            return struct.pack(float_fmt, float(sint_val))
        else:
            raise NotImplementedError(f"Unknown VUnaryOp: {self.op}")


@dataclass
class ReadRegWord(TrackedKInstr):
    """Read a word from the register file and send it back to the lamlet."""
    src: int
    j_in_k_index: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        src_preg = kamlet.r(self.src)
        await kamlet.wait_for_rf_available(
            read_regs=[src_preg], instr_ident=self.instr_ident,
        )
        jamlet = kamlet.jamlets[self.j_in_k_index]
        wb = kamlet.params.word_bytes
        byte_offset = src_preg * wb
        word = int.from_bytes(
            jamlet.rf_slice[byte_offset:byte_offset + wb], 'little',
        )
        header = IdentHeader(
            message_type=MessageType.READ_REG_WORD_RESP,
            send_type=SendType.SINGLE,
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            length=1,
            ident=self.instr_ident,
        )
        kinstr_span_id = jamlet.monitor.get_kinstr_span_id(self.instr_ident)
        await jamlet.send_packet([header, word], parent_span_id=kinstr_span_id)
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y,
        )


@dataclass
class WriteRegElement(KInstr):
    dst: int
    element_index: int
    element_width: int
    ordering: addresses.Ordering
    value: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        vw_index = self.element_index % kamlet.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            kamlet.params, self.ordering.word_order, vw_index)
        assert k_index == kamlet.k_index
        # Single-element patch: the unwritten elements must keep their old
        # values, so this is semantically RMW. Use rw() to reuse the existing
        # phys rather than rotating in a fresh (uninitialised) one.
        dst_preg = kamlet.rw(self.dst)
        await kamlet.wait_for_rf_available(
            write_regs=[dst_preg], instr_ident=self.instr_ident,
        )
        jamlet = kamlet.jamlets[j_in_k_index]
        element_in_jamlet = self.element_index // kamlet.params.j_in_l
        eb = self.element_width // 8
        base_addr = dst_preg * kamlet.params.word_bytes
        byte_offset = base_addr + element_in_jamlet * eb
        value_bytes = self.value.to_bytes(eb, byteorder='little', signed=True)
        jamlet.rf_slice[byte_offset:byte_offset + eb] = value_bytes
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y,
        )


FLOAT_OPS = (
    VArithOp.FADD, VArithOp.FSUB, VArithOp.FRSUB,
    VArithOp.FMUL, VArithOp.FDIV, VArithOp.FRDIV,
    VArithOp.FMACC, VArithOp.FNMACC, VArithOp.FMADD, VArithOp.FNMADD,
    VArithOp.FMSAC, VArithOp.FNMSAC, VArithOp.FMSUB, VArithOp.FNMSUB,
    VArithOp.FMIN, VArithOp.FMAX,
)
SIGNED_INT_OPS = (
    VArithOp.ADD, VArithOp.SUB, VArithOp.RSUB, VArithOp.MUL,
    VArithOp.MACC, VArithOp.MADD, VArithOp.NMSAC, VArithOp.NMSUB,
    VArithOp.AND, VArithOp.OR, VArithOp.XOR,
    VArithOp.SLL, VArithOp.SRA, VArithOp.MIN, VArithOp.MAX,
)
UNSIGNED_INT_OPS = (VArithOp.MINU, VArithOp.MAXU, VArithOp.SRL)
# Ops where vd is both source (accumulator) and destination.
ACCUM_OPS = (
    VArithOp.MACC, VArithOp.MADD, VArithOp.NMSAC, VArithOp.NMSUB,
    VArithOp.FMACC, VArithOp.FNMACC, VArithOp.FMADD, VArithOp.FNMADD,
    VArithOp.FMSAC, VArithOp.FNMSAC, VArithOp.FMSUB, VArithOp.FNMSUB,
)


def _compute_arith(op, src1_val, src2_val, acc_val, eb):
    """Compute the result of a vector arithmetic operation.

    src1_val: first source (vs1 for VV, scalar for VX)
    src2_val: second source (vs2)
    acc_val: accumulator value (vd, only used for ACCUM_OPS)
    eb: element width in bytes (only used for shift masking)
    """
    if op == VArithOp.ADD or op == VArithOp.FADD:
        return src2_val + src1_val
    elif op == VArithOp.SUB or op == VArithOp.FSUB:
        return src2_val - src1_val
    elif op == VArithOp.RSUB or op == VArithOp.FRSUB:
        return src1_val - src2_val
    elif op == VArithOp.MUL or op == VArithOp.FMUL:
        return src1_val * src2_val
    elif op == VArithOp.FDIV:
        return src2_val / src1_val
    elif op == VArithOp.FRDIV:
        return src1_val / src2_val
    elif op == VArithOp.AND:
        return src1_val & src2_val
    elif op == VArithOp.OR:
        return src1_val | src2_val
    elif op == VArithOp.XOR:
        return src1_val ^ src2_val
    elif op == VArithOp.SLL:
        return src2_val << (src1_val & (eb * 8 - 1))
    elif op == VArithOp.SRL:
        return src2_val >> (src1_val & (eb * 8 - 1))
    elif op == VArithOp.SRA:
        return src2_val >> (src1_val & (eb * 8 - 1))
    elif op == VArithOp.MIN or op == VArithOp.FMIN:
        return min(src1_val, src2_val)
    elif op == VArithOp.MAX or op == VArithOp.FMAX:
        return max(src1_val, src2_val)
    elif op == VArithOp.MINU:
        return min(src1_val, src2_val)
    elif op == VArithOp.MAXU:
        return max(src1_val, src2_val)
    elif op == VArithOp.MACC or op == VArithOp.FMACC:
        return (src1_val * src2_val) + acc_val
    elif op == VArithOp.FNMACC:
        return -(src1_val * src2_val) - acc_val
    elif op == VArithOp.FMSAC:
        return (src1_val * src2_val) - acc_val
    elif op == VArithOp.NMSAC or op == VArithOp.FNMSAC:
        return acc_val - (src1_val * src2_val)
    elif op == VArithOp.MADD or op == VArithOp.FMADD:
        return (src1_val * acc_val) + src2_val
    elif op == VArithOp.FNMADD:
        return -(src1_val * acc_val) - src2_val
    elif op == VArithOp.FMSUB:
        return (src1_val * acc_val) - src2_val
    elif op == VArithOp.NMSUB or op == VArithOp.FNMSUB:
        return src2_val - (src1_val * acc_val)
    else:
        raise NotImplementedError(f"Unknown arith op: {op}")


def _arith_fmt(op, eb):
    """Return struct format string for the given op and element byte width."""
    if op in FLOAT_OPS:
        return {8: 'd', 4: 'f', 2: 'e'}[eb]
    elif op in UNSIGNED_INT_OPS:
        return {8: '<Q', 4: '<I', 2: '<H', 1: '<B'}[eb]
    elif op in SIGNED_INT_OPS:
        return {8: '<q', 4: '<i', 2: '<h', 1: '<b'}[eb]
    else:
        raise NotImplementedError(f"Unknown op category: {op}")


def _arith_truncate_int(op, result, eb):
    """Truncate integer result to element width, handling signed overflow."""
    if op in FLOAT_OPS:
        return result
    mask = (1 << (eb * 8)) - 1
    result = result & mask
    if op in SIGNED_INT_OPS and result >= (1 << (eb * 8 - 1)):
        result -= (1 << (eb * 8))
    return result


@dataclass
class VArithVvOp(KInstr):
    op: VArithOp
    dst: int
    src1: int
    src2: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS
        elements_in_vline = bits_in_vline // self.element_width

        # Rename: lookup source physes before allocating dst physes so that
        # a src arch overlapping dst arch resolves to the old phys.
        src1_pregs = [kamlet.r(self.src1 + i) for i in range(n_vlines)]
        src2_pregs = [kamlet.r(self.src2 + i) for i in range(n_vlines)]
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        if is_accum:
            # Accumulator RMW: reuse existing phys (no rename rotation —
            # iter-to-iter RAW is inherent, rotation would just drain the
            # free queue). Write lock alone covers the accumulator read.
            dst_pregs = [kamlet.rw(self.dst + i) for i in range(n_vlines)]
        else:
            # n_elements operates on elements 0..n_elements-1 (start_index=0
            # for the per-element arith ops).
            dst_pregs = kamlet.alloc_dst_pregs(
                base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
                start_index=0, n_elements=self.n_elements,
                elements_in_vline=elements_in_vline,
                mask_present=self.mask_reg is not None)

        read_regs = list(src1_pregs) + list(src2_pregs)
        write_regs = list(dst_pregs)
        await kamlet.wait_for_rf_available(read_regs=read_regs, write_regs=write_regs,
                                           instr_ident=self.instr_ident)

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                src1_base = src1_pregs[vline_index] * wb
                src2_base = src2_pregs[vline_index] * wb
                dst_base = dst_pregs[vline_index] * wb
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, mask_preg,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        src1_bytes = jamlet.rf_slice[src1_base + byte_offset:src1_base + byte_offset + eb]
                        src2_bytes = jamlet.rf_slice[src2_base + byte_offset:src2_base + byte_offset + eb]
                        fmt = _arith_fmt(self.op, eb)
                        src1_val = struct.unpack(fmt, src1_bytes)[0]
                        src2_val = struct.unpack(fmt, src2_bytes)[0]
                        acc_val = None
                        if is_accum:
                            acc_bytes = jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                        result = _compute_arith(self.op, src1_val, src2_val, acc_val, eb)
                        result = _arith_truncate_int(self.op, result, eb)
                        jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb] = struct.pack(fmt, result)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VArithVxOp(KInstr):
    op: VArithOp
    dst: int
    scalar_bytes: bytes
    src2: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int
    is_float: bool = False

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS
        elements_in_vline = bits_in_vline // self.element_width

        # Rename: lookup source physes before allocating dst physes so that
        # a src arch overlapping dst arch resolves to the old phys.
        src2_pregs = [kamlet.r(self.src2 + i) for i in range(n_vlines)]
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        if is_accum:
            dst_pregs = [kamlet.rw(self.dst + i) for i in range(n_vlines)]
        else:
            dst_pregs = kamlet.alloc_dst_pregs(
                base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
                start_index=0, n_elements=self.n_elements,
                elements_in_vline=elements_in_vline,
                mask_present=self.mask_reg is not None)

        read_regs = list(src2_pregs)
        write_regs = list(dst_pregs)
        await kamlet.wait_for_rf_available(read_regs=read_regs, write_regs=write_regs,
                                           instr_ident=self.instr_ident)

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes

        fmt = _arith_fmt(self.op, eb)
        scalar_val = struct.unpack(fmt, self.scalar_bytes[:eb])[0]
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                src2_base = src2_pregs[vline_index] * wb
                dst_base = dst_pregs[vline_index] * wb
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        mask_preg, vline_index, j_in_k_index, index_in_j)
                    if valid_element and mask_bit:
                        src2_bytes = jamlet.rf_slice[src2_base + byte_offset:src2_base + byte_offset + eb]
                        src2_val = struct.unpack(fmt, src2_bytes)[0]
                        acc_val = None
                        if is_accum:
                            acc_bytes = jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                        result = _compute_arith(self.op, scalar_val, src2_val, acc_val, eb)
                        result = _arith_truncate_int(self.op, result, eb)
                        jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb] = struct.pack(fmt, result)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VreductionOp(KInstr):
    op: VRedOp
    dst: int
    src_vector: int
    src_scalar_reg: int
    mask_reg: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        await kamlet.handle_vreduction_instr(self)



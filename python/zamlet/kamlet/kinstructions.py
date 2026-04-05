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
    MUL = "mul"
    MACC = "macc"
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
    FMADD = "fmadd"
    FMIN = "fmin"
    FMAX = "fmax"


class VUnaryOp(Enum):
    COPY = "copy"
    SEXT = "sext"
    ZEXT = "zext"
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
    SUM = "sum"
    MAXU = "maxu"
    MAX = "max"
    MINU = "minu"
    MIN = "min"
    AND = "and"
    OR = "or"
    XOR = "xor"


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


def _vcmp_write_bit(rf_slice, base_dst_bit_addr, element_in_jamlet, result_bit):
    """Write a single result bit to the destination mask register."""
    dst_bit_addr = base_dst_bit_addr + element_in_jamlet
    dst_byte_addr = dst_bit_addr // 8
    dst_bit_offset = dst_bit_addr % 8
    if result_bit:
        rf_slice[dst_byte_addr] |= (1 << dst_bit_offset)
    else:
        rf_slice[dst_byte_addr] &= ~(1 << dst_bit_offset)


def _vcmp_dst_regs(dst, n_elements, vline_bytes):
    elements_in_dst_vline = vline_bytes * 8  # 1 bit per element
    n_dst_vlines = (n_elements + elements_in_dst_vline - 1) // elements_in_dst_vline
    return [dst + index for index in range(n_dst_vlines)]


def _vcmp_src_regs(src, n_elements, element_width, vline_bytes):
    elements_in_src_vline = vline_bytes * 8 // element_width
    n_src_vlines = (n_elements + elements_in_src_vline - 1) // elements_in_src_vline
    return [src + index for index in range(n_src_vlines)]


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
        src_regs = _vcmp_src_regs(
            self.src, self.n_elements, self.element_width, kamlet.params.vline_bytes,
        )
        dst_regs = _vcmp_dst_regs(self.dst, self.n_elements, kamlet.params.vline_bytes)

        await kamlet.wait_for_rf_available(
            read_regs=src_regs, write_regs=dst_regs, instr_ident=self.instr_ident,
        )
        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)

        base_src_bit_addr = self.src * kamlet.params.word_bytes * 8
        base_dst_bit_addr = self.dst * kamlet.params.word_bytes * 8

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index // kamlet.params.j_in_l
            if k_index == kamlet.k_index:
                jamlet = kamlet.jamlets[j_in_k_index]
                src_bit_addr = base_src_bit_addr + element_in_jamlet * self.element_width
                assert src_bit_addr % 8 == 0
                eb = self.element_width // 8
                src_bytes = jamlet.rf_slice[src_bit_addr // 8:src_bit_addr // 8 + eb]
                src_val = int.from_bytes(
                    src_bytes, byteorder='little', signed=not unsigned,
                )
                result_bit = _vcmp_evaluate(self.op, src_val, sign_extended_imm)
                _vcmp_write_bit(
                    jamlet.rf_slice, base_dst_bit_addr, element_in_jamlet, result_bit,
                )
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
        src_regs = _vcmp_src_regs(
            self.src1, self.n_elements, self.element_width, kamlet.params.vline_bytes,
        )
        src_regs += _vcmp_src_regs(
            self.src2, self.n_elements, self.element_width, kamlet.params.vline_bytes,
        )
        dst_regs = _vcmp_dst_regs(self.dst, self.n_elements, kamlet.params.vline_bytes)

        await kamlet.wait_for_rf_available(
            read_regs=src_regs, write_regs=dst_regs, instr_ident=self.instr_ident,
        )
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)

        base_src1_bit_addr = self.src1 * kamlet.params.word_bytes * 8
        base_src2_bit_addr = self.src2 * kamlet.params.word_bytes * 8
        base_dst_bit_addr = self.dst * kamlet.params.word_bytes * 8

        for element_index in range(self.n_elements):
            vw_index = element_index % kamlet.params.j_in_l
            k_index, j_in_k_index = addresses.vw_index_to_k_indices(
                kamlet.params, self.ordering.word_order, vw_index)
            element_in_jamlet = element_index // kamlet.params.j_in_l
            if k_index == kamlet.k_index:
                jamlet = kamlet.jamlets[j_in_k_index]
                src_bit_addr = element_in_jamlet * self.element_width
                assert src_bit_addr % 8 == 0
                eb = self.element_width // 8
                s1_off = base_src1_bit_addr // 8 + src_bit_addr // 8
                s2_off = base_src2_bit_addr // 8 + src_bit_addr // 8
                src1_bytes = jamlet.rf_slice[s1_off:s1_off + eb]
                src2_bytes = jamlet.rf_slice[s2_off:s2_off + eb]
                src1_val = int.from_bytes(
                    src1_bytes, byteorder='little', signed=not unsigned,
                )
                src2_val = int.from_bytes(
                    src2_bytes, byteorder='little', signed=not unsigned,
                )
                result_bit = _vcmp_evaluate(self.op, src2_val, src1_val)
                _vcmp_write_bit(
                    jamlet.rf_slice, base_dst_bit_addr, element_in_jamlet, result_bit,
                )
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VmnandMmOp(KInstr):
    dst: int
    src1: int
    src2: int
    instr_ident: int

    async def update_kamlet(self, kamlet):
        read_regs = []
        if self.src1 != self.dst:
            read_regs.append(self.src1)
        if self.src2 != self.dst and self.src2 not in read_regs:
            read_regs.append(self.src2)
        await kamlet.wait_for_rf_available(read_regs=read_regs, write_regs=[self.dst],
                                           instr_ident=self.instr_ident)

        wb = kamlet.params.word_bytes
        for jamlet in kamlet.jamlets:
            for byte_offset in range(wb):
                src1_byte = jamlet.rf_slice[self.src1 * wb + byte_offset]
                src2_byte = jamlet.rf_slice[self.src2 * wb + byte_offset]
                result_byte = ~(src1_byte & src2_byte) & 0xff
                jamlet.rf_slice[self.dst * wb + byte_offset] = result_byte
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VBroadcastOp(KInstr):
    """Broadcast a scalar value to all elements of a vector register.

    Used for vmv.v.i, vmv.v.x instructions.
    """
    dst: int
    scalar: int
    n_elements: int
    element_width: int
    word_order: addresses.WordOrder
    instr_ident: int

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(write_regs=dst_regs, instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, None,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element:
                        result_bytes = self.scalar.to_bytes(eb, byteorder='little', signed=True)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = result_bytes
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
        dst_regs = [self.dst + index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(write_regs=dst_regs, instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0
        elements_in_vline = params.vline_bytes * 8 // self.element_width

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            vw_index = addresses.k_indices_to_vw_index(
                params, self.word_order, kamlet.k_index, j_in_k_index)
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    element_index = (vline_index * elements_in_vline +
                                     index_in_j * params.j_in_l + vw_index)
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        self.mask_reg, vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        result_bytes = element_index.to_bytes(eb, byteorder='little', signed=False)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = (
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

    async def update_kamlet(self, kamlet):
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        n_src_vlines = (self.n_elements * self.src_ew + bits_in_vline - 1) // bits_in_vline
        dst_regs = [self.dst + i for i in range(n_dst_vlines)]
        src_regs = [self.src + i for i in range(n_src_vlines)]
        read_regs = list(src_regs)
        if self.mask_reg is not None:
            read_regs.append(self.mask_reg)
        await kamlet.wait_for_rf_available(
            read_regs=read_regs, write_regs=dst_regs, instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src_base = self.src * vreg_bytes_per_jamlet
        dst_base = self.dst * vreg_bytes_per_jamlet
        src_eb = self.src_ew // 8
        dst_eb = self.dst_ew // 8
        wb = params.word_bytes

        dst_elements_per_word = wb // dst_eb
        src_elements_per_word = wb // src_eb
        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_dst_vlines):
                for index_in_j in range(dst_elements_per_word):
                    valid_element, mask_bit = kamlet.get_is_active(
                        0, self.n_elements, self.dst_ew, self.word_order,
                        self.mask_reg, vline_index, j_in_k_index, index_in_j)
                    if not (valid_element and mask_bit):
                        continue
                    # Element index within this jamlet
                    dst_elem = vline_index * dst_elements_per_word + index_in_j
                    # Same element in the source layout
                    src_vline = dst_elem // src_elements_per_word
                    src_idx = dst_elem % src_elements_per_word
                    dst_byte = dst_base + vline_index * wb + index_in_j * dst_eb
                    src_byte = src_base + src_vline * wb + src_idx * src_eb
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
        await kamlet.wait_for_rf_available(
            read_regs=[self.src], instr_ident=self.instr_ident,
        )
        jamlet = kamlet.jamlets[self.j_in_k_index]
        wb = kamlet.params.word_bytes
        byte_offset = self.src * wb
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
        await kamlet.wait_for_rf_available(
            write_regs=[self.dst], instr_ident=self.instr_ident,
        )
        jamlet = kamlet.jamlets[j_in_k_index]
        element_in_jamlet = self.element_index // kamlet.params.j_in_l
        eb = self.element_width // 8
        base_addr = self.dst * kamlet.params.word_bytes
        byte_offset = base_addr + element_in_jamlet * eb
        value_bytes = self.value.to_bytes(eb, byteorder='little', signed=True)
        jamlet.rf_slice[byte_offset:byte_offset + eb] = value_bytes
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y,
        )


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
        src_regs = [self.src1+index for index in range(n_vlines)]
        src_regs += [self.src2+index for index in range(n_vlines)]
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs,
                                           instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src1_offset = self.src1 * vreg_bytes_per_jamlet
        src2_offset = self.src2 * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order, self.mask_reg,
                        vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        src1_bytes = jamlet.rf_slice[src1_offset + byte_offset:src1_offset + byte_offset + eb]
                        src2_bytes = jamlet.rf_slice[src2_offset + byte_offset:src2_offset + byte_offset + eb]
                        float_ops = (VArithOp.FADD, VArithOp.FSUB, VArithOp.FMUL, VArithOp.FDIV,
                                     VArithOp.FMACC, VArithOp.FMADD, VArithOp.FMIN, VArithOp.FMAX)
                        signed_int_ops = (VArithOp.ADD, VArithOp.SUB, VArithOp.MUL, VArithOp.MACC,
                                          VArithOp.AND, VArithOp.OR, VArithOp.XOR,
                                          VArithOp.SLL, VArithOp.SRA, VArithOp.MIN, VArithOp.MAX)
                        unsigned_int_ops = (VArithOp.MINU, VArithOp.MAXU, VArithOp.SRL)
                        if self.op in float_ops:
                            fmt = {8: 'd', 4: 'f', 2: 'e'}[eb]
                        elif self.op in signed_int_ops:
                            fmt = {8: '<q', 4: '<i', 2: '<h', 1: '<b'}[eb]
                        elif self.op in unsigned_int_ops:
                            fmt = {8: '<Q', 4: '<I', 2: '<H', 1: '<B'}[eb]
                        else:
                            raise NotImplementedError(f"Unknown op: {self.op}")
                        src1_val = struct.unpack(fmt, src1_bytes)[0]
                        src2_val = struct.unpack(fmt, src2_bytes)[0]

                        if self.op == VArithOp.ADD:
                            result = src1_val + src2_val
                        elif self.op == VArithOp.SUB:
                            result = src2_val - src1_val
                        elif self.op == VArithOp.MUL:
                            result = src1_val * src2_val
                        elif self.op == VArithOp.MACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                            result = (src1_val * src2_val) + acc_val
                        elif self.op == VArithOp.AND:
                            result = src1_val & src2_val
                        elif self.op == VArithOp.OR:
                            result = src1_val | src2_val
                        elif self.op == VArithOp.XOR:
                            result = src1_val ^ src2_val
                        elif self.op == VArithOp.SLL:
                            result = src2_val << (src1_val & (eb * 8 - 1))
                        elif self.op == VArithOp.SRL:
                            result = src2_val >> (src1_val & (eb * 8 - 1))
                        elif self.op == VArithOp.SRA:
                            result = src2_val >> (src1_val & (eb * 8 - 1))
                        elif self.op == VArithOp.MIN:
                            result = min(src1_val, src2_val)
                        elif self.op == VArithOp.MAX:
                            result = max(src1_val, src2_val)
                        elif self.op == VArithOp.MINU:
                            result = min(src1_val, src2_val)
                        elif self.op == VArithOp.MAXU:
                            result = max(src1_val, src2_val)
                        elif self.op == VArithOp.FADD:
                            result = src2_val + src1_val
                        elif self.op == VArithOp.FSUB:
                            result = src2_val - src1_val
                        elif self.op == VArithOp.FMUL:
                            result = src2_val * src1_val
                        elif self.op == VArithOp.FDIV:
                            result = src2_val / src1_val
                        elif self.op == VArithOp.FMACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                            result = (src1_val * src2_val) + acc_val
                        elif self.op == VArithOp.FMADD:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                            result = (src1_val * acc_val) + src2_val
                        elif self.op == VArithOp.FMIN:
                            result = min(src1_val, src2_val)
                        elif self.op == VArithOp.FMAX:
                            result = max(src1_val, src2_val)
                        else:
                            raise NotImplementedError(f"Unknown op: {self.op}")

                        # Truncate integer results to element width (handles overflow from SLL, ADD, etc.)
                        if self.op in signed_int_ops or self.op in unsigned_int_ops:
                            mask = (1 << (eb * 8)) - 1
                            result = result & mask
                            # For signed formats, convert back to signed range
                            if self.op in signed_int_ops and result >= (1 << (eb * 8 - 1)):
                                result -= (1 << (eb * 8))

                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = struct.pack(fmt, result)
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
        import struct
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        src_regs = [self.src2+index for index in range(n_vlines)]
        dst_regs = [self.dst+index for index in range(n_vlines)]
        await kamlet.wait_for_rf_available(read_regs=src_regs, write_regs=dst_regs,
                                           instr_ident=self.instr_ident)

        params = kamlet.params
        vreg_bytes_per_jamlet = params.maxvl_bytes // params.j_in_l
        src2_offset = self.src2 * vreg_bytes_per_jamlet
        dst_offset = self.dst * vreg_bytes_per_jamlet
        eb = self.element_width // 8
        wb = kamlet.params.word_bytes

        if self.is_float:
            fmt_code = 'd' if self.element_width == 64 else 'f'
            unpack = lambda b: struct.unpack(fmt_code, b)[0]
            pack = lambda v: struct.pack(fmt_code, v)
        else:
            unpack = lambda b: int.from_bytes(b, byteorder='little', signed=True)
            pack = lambda v: v.to_bytes(eb, byteorder='little', signed=True)

        scalar_val = unpack(self.scalar_bytes[:eb])
        start_index = 0

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                for index_in_j in range(wb // eb):
                    byte_offset = vline_index * wb + index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        self.mask_reg, vline_index, j_in_k_index, index_in_j)
                    if valid_element and mask_bit:
                        src2_bytes = jamlet.rf_slice[src2_offset + byte_offset:src2_offset + byte_offset + eb]
                        src2_val = unpack(src2_bytes)

                        if self.op == VArithOp.ADD:
                            result = src2_val + scalar_val
                        elif self.op == VArithOp.SUB:
                            result = src2_val - scalar_val
                        elif self.op == VArithOp.MUL:
                            result = src2_val * scalar_val
                        elif self.op == VArithOp.MACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = unpack(acc_bytes)
                            result = acc_val + (scalar_val * src2_val)
                        elif self.op == VArithOp.FMACC:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = unpack(acc_bytes)
                            result = (scalar_val * src2_val) + acc_val
                        elif self.op == VArithOp.FMADD:
                            acc_bytes = jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb]
                            acc_val = unpack(acc_bytes)
                            result = (scalar_val * acc_val) + src2_val
                        elif self.op == VArithOp.AND:
                            result = src2_val & scalar_val
                        elif self.op == VArithOp.OR:
                            result = src2_val | scalar_val
                        elif self.op == VArithOp.XOR:
                            result = src2_val ^ scalar_val
                        elif self.op == VArithOp.SLL:
                            shift_amt = scalar_val & (self.element_width - 1)
                            result = src2_val << shift_amt
                        elif self.op == VArithOp.SRL:
                            shift_amt = scalar_val & (self.element_width - 1)
                            src2_unsigned = int.from_bytes(src2_bytes, byteorder='little', signed=False)
                            result = src2_unsigned >> shift_amt
                        elif self.op == VArithOp.SRA:
                            shift_amt = scalar_val & (self.element_width - 1)
                            result = src2_val >> shift_amt
                        else:
                            raise NotImplementedError(f"VArithVxOp: unknown op {self.op}")

                        # Truncate result to element width (handles overflow from SLL, ADD, MUL, etc.)
                        if not self.is_float:
                            mask = (1 << (eb * 8)) - 1
                            result = result & mask
                            # Convert back to signed for pack
                            if result >= (1 << (eb * 8 - 1)):
                                result -= (1 << (eb * 8))

                        result_bytes = pack(result)
                        jamlet.rf_slice[dst_offset + byte_offset:dst_offset + byte_offset + eb] = result_bytes
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VreductionVsOp(KInstr):
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
        await kamlet.handle_vreduction_vs_instr(self)



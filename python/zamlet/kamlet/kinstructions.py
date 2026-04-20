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

import copy
import logging
import struct
from dataclasses import dataclass, field
from enum import Enum, IntEnum

from zamlet import addresses
from zamlet.addresses import KMAddr, GlobalAddress
from zamlet.params import ZamletParams
from zamlet.control_structures import pack_fields_to_int
from zamlet.message import IdentHeader, MessageType, SendType, WriteMemWordHeader
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
    FSGNJ = "fsgnj"
    FSGNJN = "fsgnjn"
    FSGNJX = "fsgnjx"


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
    GE = "sge"


class VmLogicOp(Enum):
    """Vector mask-mask logical ops (vm*.mm).

    Operand convention per RVV: `vm<op>.mm vd, vs2, vs1` — the first kinstr
    source (src1) is always vs2 and the second (src2) is vs1.
    """
    AND = "vmand"
    ANDN = "vmandn"
    OR = "vmor"
    ORN = "vmorn"
    XOR = "vmxor"
    NAND = "vmnand"
    NOR = "vmnor"
    XNOR = "vmxnor"


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


@dataclass
class Renamed:
    """Renamed state for an instruction in the reservation station.

    Populated by KInstr.admit(). The reservation station uses the
    readiness fields to decide when an instruction is ready to execute,
    and execute() uses the phys reg mappings to access the RF.

    Preg mapping dicts are keyed by vline offset from the base arch
    register. By role convention (used to derive read/write scoreboard
    views): src_pregs, src2_pregs, and mask_preg are reads; dst_pregs
    is writes.
    """
    order: int = 0
    writes_all_memory: bool = False
    reads_all_memory: bool = False
    cache_is_read: bool = False
    cache_is_write: bool = False
    writeset_ident: int | None = None
    needs_witem: int = 0
    src_pregs: dict[int, int] = field(default_factory=dict)
    dst_pregs: dict[int, int] = field(default_factory=dict)
    src2_pregs: dict[int, int] = field(default_factory=dict)
    mask_preg: int | None = None
    index_bound_bits: int = 0
    ident_query_distance: int | None = None

    @property
    def read_pregs(self) -> list[int]:
        result = list(self.src_pregs.values())
        result.extend(self.src2_pregs.values())
        if self.mask_preg is not None:
            result.append(self.mask_preg)
        return result

    @property
    def write_pregs(self) -> list[int]:
        return list(self.dst_pregs.values())


def has_reg_ordering_conflict(this: Renamed, other: Renamed) -> bool:
    """Return True if `this` must wait for `other` due to a preg hazard.

    Covers RAW, WAW, and WAR against an earlier-order reservation station
    entry that hasn't dispatched yet. rf_info locks only catch hazards
    after the earlier entry has called rf_info.start() in execute(); this
    closes the admit-to-dispatch window. It especially matters when two
    writes target the same preg (e.g. masked-load rw() reuse for fully-
    undisturbed semantics) with a reader of that preg between them.
    """
    this_reads = set(this.read_pregs)
    this_writes = set(this.write_pregs)
    other_reads = set(other.read_pregs)
    other_writes = set(other.write_pregs)
    if other_writes & this_reads:
        return True
    if other_writes & this_writes:
        return True
    if other_reads & this_writes:
        return True
    return False


class KInstr:
    renamed: Renamed | None = None

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

    def rename(self, **kwargs) -> 'KInstr':
        """Return a shallow copy of this instruction with a new Renamed
        state constructed from kwargs.

        The same KInstr Python instance can be routed to multiple kamlets;
        each kamlet must hold its own per-instance `renamed` state or admits
        on different kamlets will stomp each other. Shallow copy suffices
        because all non-renamed fields are treated as immutable after
        construction.
        """
        new = copy.copy(self)
        new.renamed = Renamed(**kwargs)
        return new

    async def admit(self, kamlet) -> 'KInstr | None':
        """Called when popped from the instruction queue. Returns a clone
        (via rename()) to place in the reservation station, or None if the
        instruction has been fully handled in admit and needs no station
        entry or execute() call.
        """
        raise NotImplementedError(f"{type(self).__name__}.admit")

    async def execute(self, kamlet) -> None:
        """Execute after is_ready has confirmed all resource preconditions
        (RF availability, cache slot, memory ordering, witem slot). Only
        called for admit-returns-True (station-path) instructions. May
        await on things not gated by is_ready — e.g. sending a response
        packet whose output-queue backpressure can't easily be surfaced
        into is_ready.
        """
        raise NotImplementedError(f"{type(self).__name__}.execute")


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

    async def admit(self, kamlet) -> 'SetIndexBound | None':
        kamlet.index_bound_bits = self.index_bound_bits
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        return None


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

    async def admit(self, kamlet) -> 'FreeRegister | None':
        kamlet.rename_table.free_register(self.reg)
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        return None


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

    async def admit(self, kamlet) -> 'LoadImmByte | None':
        if self.dst.k_index != kamlet.k_index:
            kamlet.monitor.finalize_kinstr_exec(
                self.instr_ident, kamlet.min_x, kamlet.min_y)
            return None
        # Single-byte patch — most of the register stays unchanged, so this
        # is RMW. Use rw() to keep the existing phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_preg = kamlet.rw(self.dst.reg)
        return self.rename(
            dst_pregs={0: dst_preg}, mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        dst_preg = r.dst_pregs[0]
        jamlet = kamlet.jamlets[self.dst.j_in_k_index]
        reg_offset = self.dst.offset_in_word
        old_byte = jamlet.rf_slice[dst_preg * kamlet.params.word_bytes + reg_offset]
        new_byte = (old_byte & ~self.bit_mask) | (self.imm & self.bit_mask)
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        jamlet.write_vreg(dst_preg, reg_offset, bytes([new_byte]), span_id=span_id,
                          event_details={'bit_mask': f'0x{self.bit_mask:02x}'})
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)


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

    async def admit(self, kamlet) -> 'LoadImmWord | None':
        if self.dst.k_index != kamlet.k_index:
            kamlet.monitor.finalize_kinstr_exec(
                self.instr_ident, kamlet.min_x, kamlet.min_y)
            return None
        # Partial-word patch (only byte_mask bytes written) — RMW. Use rw().
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_preg = kamlet.rw(self.dst.reg)
        return self.rename(
            dst_pregs={0: dst_preg}, mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        dst_preg = r.dst_pregs[0]
        jamlet = kamlet.jamlets[self.dst.j_in_k_index]
        wb = kamlet.params.word_bytes
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        for byte_idx in range(wb):
            if self.byte_mask & (1 << byte_idx):
                jamlet.write_vreg(dst_preg, byte_idx, bytes([self.imm[byte_idx]]),
                                  span_id=span_id,
                                  event_details={'byte_mask': f'0x{self.byte_mask:02x}'})
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

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

    async def admit(self, kamlet) -> 'StoreScalar | None':
        assert self.src.k_index == kamlet.k_index
        src_preg = kamlet.r(self.src.reg)
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        return self.rename(
            src_pregs={0: src_preg}, mask_preg=mask_preg)

    async def execute(self, kamlet) -> None:
        r = self.renamed
        src_preg = r.src_pregs[0]
        rf_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        jamlet = kamlet.jamlets[self.src.j_in_k_index]
        wb = kamlet.params.word_bytes
        src_word = int.from_bytes(
            jamlet.rf_slice[src_preg * wb: (src_preg + 1) * wb], 'little')
        logger.debug(
            f'StoreScalar: kamlet ({kamlet.min_x},{kamlet.min_y}) '
            f'reg={self.src.reg} src_word=0x{src_word:x} '
            f'scalar_addr=0x{self.scalar_addr:x} tag={0} '
            f'dst_byte_in_word={self.dst_byte_in_word} n_bytes={self.n_bytes_or_bits}')
        kamlet.rf_info.finish(
            rf_ident, read_regs=r.read_pregs, write_regs=r.write_pregs)

        header = WriteMemWordHeader(
            target_x=jamlet.lamlet_x,
            target_y=jamlet.lamlet_y,
            source_x=jamlet.x,
            source_y=jamlet.y,
            message_type=MessageType.WRITE_MEM_WORD_REQ,
            send_type=SendType.SINGLE,
            length=2,
            ident=self.instr_ident,
            tag=self.src.offset_in_word,
            dst_byte_in_word=self.dst_byte_in_word,
            n_bytes_or_bits=self.n_bytes_or_bits,
            bit_mode=self.bit_mode,
            dst_bit_in_byte=self.dst_bit_in_byte,
            no_response=True,
            writeset_ident=self.writeset_ident,
        )
        packet = [header, self.scalar_addr, src_word]

        kinstr_exec_span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        await jamlet.send_packet(packet, parent_span_id=kinstr_exec_span_id)

        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        kamlet.monitor.release_kinstr_ident(self.instr_ident)


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
    elif op == VCmpOp.GE:
        return 1 if a >= b else 0
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

    async def admit(self, kamlet) -> 'VCmpViOp | None':
        vline_bytes = kamlet.params.vline_bytes
        n_src_vlines = (self.n_elements * self.element_width + vline_bytes * 8 - 1) // (
            vline_bytes * 8)
        n_dst_vlines = (self.n_elements + vline_bytes * 8 - 1) // (vline_bytes * 8)
        dst_elements_in_vline = vline_bytes * 8

        # Rename: lookup src physes before allocating dst physes.
        src_pregs = [kamlet.r(self.src + i) for i in range(n_src_vlines)]
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline, mask_present=False,
            exclude_reuse=set(src_pregs))
        return self.rename(
            src_pregs={v: src_pregs[v] for v in range(n_src_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_dst_vlines)},
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        wb = kamlet.params.word_bytes
        bits_per_jamlet_vline = wb * 8
        sign_extended_imm = self.simm5 if self.simm5 < 16 else self.simm5 - 32
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)
        eb = self.element_width // 8
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

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
            src_base = r.src_pregs[src_vline_idx] * wb
            src_bytes = jamlet.rf_slice[src_base + src_byte_in_vline:
                                        src_base + src_byte_in_vline + eb]
            src_val = int.from_bytes(src_bytes, byteorder='little', signed=not unsigned)
            result_bit = _vcmp_evaluate(self.op, src_val, sign_extended_imm)

            dst_bit_in_jvec = element_in_jamlet
            dst_vline_idx = dst_bit_in_jvec // bits_per_jamlet_vline
            dst_bit_in_vline = dst_bit_in_jvec % bits_per_jamlet_vline
            dst_byte_in_vline = dst_bit_in_vline // 8
            dst_bit_offset = dst_bit_in_vline % 8
            dst_preg = r.dst_pregs[dst_vline_idx]
            old_byte = jamlet.rf_slice[dst_preg * wb + dst_byte_in_vline]
            if result_bit:
                new_byte = old_byte | (1 << dst_bit_offset)
            else:
                new_byte = old_byte & ~(1 << dst_bit_offset)
            jamlet.write_vreg(dst_preg, dst_byte_in_vline, bytes([new_byte]),
                              span_id=span_id,
                              event_details={'element_index': element_index,
                                             'bit': dst_bit_offset,
                                             'result': bool(result_bit)})

        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


_CMP_FLOAT_FMT = {8: '<d', 4: '<f', 2: '<e'}


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
    is_float: bool = False

    async def admit(self, kamlet) -> 'VCmpVxOp | None':
        vline_bytes = kamlet.params.vline_bytes
        n_src_vlines = (self.n_elements * self.element_width + vline_bytes * 8 - 1) // (
            vline_bytes * 8)
        n_dst_vlines = (self.n_elements + vline_bytes * 8 - 1) // (vline_bytes * 8)
        dst_elements_in_vline = vline_bytes * 8

        # Rename: lookup src physes before allocating dst physes.
        src_pregs = [kamlet.r(self.src + i) for i in range(n_src_vlines)]
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline, mask_present=False,
            exclude_reuse=set(src_pregs))
        return self.rename(
            src_pregs={v: src_pregs[v] for v in range(n_src_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_dst_vlines)},
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        wb = kamlet.params.word_bytes
        bits_per_jamlet_vline = wb * 8
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)
        eb = self.element_width // 8
        if self.is_float:
            fmt = _CMP_FLOAT_FMT[eb]
            scalar_val = struct.unpack(fmt, self.scalar_bytes[:eb])[0]
        else:
            scalar_val = int.from_bytes(
                self.scalar_bytes[:eb], byteorder='little', signed=not unsigned,
            )
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

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
            src_base = r.src_pregs[src_vline_idx] * wb
            src_bytes = jamlet.rf_slice[src_base + src_byte_in_vline:
                                        src_base + src_byte_in_vline + eb]
            if self.is_float:
                src_val = struct.unpack(fmt, src_bytes)[0]
            else:
                src_val = int.from_bytes(src_bytes, byteorder='little', signed=not unsigned)
            result_bit = _vcmp_evaluate(self.op, src_val, scalar_val)

            dst_bit_in_jvec = element_in_jamlet
            dst_vline_idx = dst_bit_in_jvec // bits_per_jamlet_vline
            dst_bit_in_vline = dst_bit_in_jvec % bits_per_jamlet_vline
            dst_byte_in_vline = dst_bit_in_vline // 8
            dst_bit_offset = dst_bit_in_vline % 8
            dst_preg = r.dst_pregs[dst_vline_idx]
            old_byte = jamlet.rf_slice[dst_preg * wb + dst_byte_in_vline]
            if result_bit:
                new_byte = old_byte | (1 << dst_bit_offset)
            else:
                new_byte = old_byte & ~(1 << dst_bit_offset)
            jamlet.write_vreg(dst_preg, dst_byte_in_vline, bytes([new_byte]),
                              span_id=span_id,
                              event_details={'element_index': element_index,
                                             'bit': dst_bit_offset,
                                             'result': bool(result_bit)})

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
    is_float: bool = False

    async def admit(self, kamlet) -> 'VCmpVvOp | None':
        vline_bytes = kamlet.params.vline_bytes
        n_src_vlines = (self.n_elements * self.element_width + vline_bytes * 8 - 1) // (
            vline_bytes * 8)
        n_dst_vlines = (self.n_elements + vline_bytes * 8 - 1) // (vline_bytes * 8)
        dst_elements_in_vline = vline_bytes * 8

        # Rename: lookup src physes before allocating dst physes.
        src1_pregs = [kamlet.r(self.src1 + i) for i in range(n_src_vlines)]
        src2_pregs = [kamlet.r(self.src2 + i) for i in range(n_src_vlines)]
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline, mask_present=False,
            exclude_reuse=set(src1_pregs) | set(src2_pregs))
        return self.rename(
            src_pregs={v: src1_pregs[v] for v in range(n_src_vlines)},
            src2_pregs={v: src2_pregs[v] for v in range(n_src_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_dst_vlines)},
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        wb = kamlet.params.word_bytes
        bits_per_jamlet_vline = wb * 8
        unsigned = self.op in (VCmpOp.LTU, VCmpOp.LEU, VCmpOp.GTU)
        eb = self.element_width // 8
        fmt = _CMP_FLOAT_FMT[eb] if self.is_float else None
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

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
            s1_off = r.src_pregs[src_vline_idx] * wb + src_byte_in_vline
            s2_off = r.src2_pregs[src_vline_idx] * wb + src_byte_in_vline
            src1_bytes = jamlet.rf_slice[s1_off:s1_off + eb]
            src2_bytes = jamlet.rf_slice[s2_off:s2_off + eb]
            if self.is_float:
                src1_val = struct.unpack(fmt, src1_bytes)[0]
                src2_val = struct.unpack(fmt, src2_bytes)[0]
            else:
                src1_val = int.from_bytes(src1_bytes, byteorder='little', signed=not unsigned)
                src2_val = int.from_bytes(src2_bytes, byteorder='little', signed=not unsigned)
            result_bit = _vcmp_evaluate(self.op, src2_val, src1_val)

            dst_bit_in_jvec = element_in_jamlet
            dst_vline_idx = dst_bit_in_jvec // bits_per_jamlet_vline
            dst_bit_in_vline = dst_bit_in_jvec % bits_per_jamlet_vline
            dst_byte_in_vline = dst_bit_in_vline // 8
            dst_bit_offset = dst_bit_in_vline % 8
            dst_preg = r.dst_pregs[dst_vline_idx]
            old_byte = jamlet.rf_slice[dst_preg * wb + dst_byte_in_vline]
            if result_bit:
                new_byte = old_byte | (1 << dst_bit_offset)
            else:
                new_byte = old_byte & ~(1 << dst_bit_offset)
            jamlet.write_vreg(dst_preg, dst_byte_in_vline, bytes([new_byte]),
                              span_id=span_id,
                              event_details={'element_index': element_index,
                                             'bit': dst_bit_offset,
                                             'result': bool(result_bit)})

        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


def _vmlogic_eval(op: VmLogicOp, a: int, b: int) -> int:
    """Apply an 8-bit-wide mask-mask logical op.

    Per the VmLogicOp docstring, `a` carries the kinstr's src1 bits (= RVV vs2)
    and `b` carries src2 (= RVV vs1).
    """
    a &= 0xff
    b &= 0xff
    if op == VmLogicOp.AND:
        return a & b
    if op == VmLogicOp.ANDN:
        return a & (~b & 0xff)
    if op == VmLogicOp.OR:
        return a | b
    if op == VmLogicOp.ORN:
        return a | (~b & 0xff)
    if op == VmLogicOp.XOR:
        return a ^ b
    if op == VmLogicOp.NAND:
        return (~(a & b)) & 0xff
    if op == VmLogicOp.NOR:
        return (~(a | b)) & 0xff
    if op == VmLogicOp.XNOR:
        return (~(a ^ b)) & 0xff
    raise NotImplementedError(f"Unknown VmLogicOp: {op}")


@dataclass
class VmLogicMmOp(KInstr):
    """Vector mask-mask logical op (vm{and,andn,or,orn,xor,nand,nor,xnor}.mm).

    dst.mask[i] = op(src1.mask[i], src2.mask[i]) for i in [start_index, n_elements).
    Elements outside that range are left undisturbed under the current
    fully-undisturbed policy (vta=vma=False).

    Mask registers are laid out at ew=1 (one bit per element). Sources and
    destination must already be at ew=1; the lamlet wrapper asserts this.
    """
    op: VmLogicOp
    dst: int
    src1: int
    src2: int
    start_index: int
    n_elements: int
    word_order: addresses.WordOrder
    instr_ident: int

    def _vline_range(self, kamlet) -> tuple[int, int] | None:
        """Return (start_vline, end_vline) inclusive, or None for no-op.

        No-op cases: n_elements == 0 (empty vector), or start_index >= n_elements
        (the active region [start_index, n_elements) is empty).
        """
        if self.n_elements == 0 or self.start_index >= self.n_elements:
            return None
        elements_in_vline = kamlet.params.vline_bytes * 8
        start_vline = self.start_index // elements_in_vline
        end_vline = (self.n_elements - 1) // elements_in_vline
        return start_vline, end_vline

    async def admit(self, kamlet) -> 'VmLogicMmOp | None':
        vrange = self._vline_range(kamlet)
        if vrange is None:
            return self.rename()
        start_vline, end_vline = vrange
        elements_in_vline = kamlet.params.vline_bytes * 8

        src1_pregs = {v: kamlet.r(self.src1 + v)
                      for v in range(start_vline, end_vline + 1)}
        src2_pregs = {v: kamlet.r(self.src2 + v)
                      for v in range(start_vline, end_vline + 1)}
        dst_pregs_list = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=start_vline, end_vline=end_vline,
            start_index=self.start_index, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline, mask_present=False,
            exclude_reuse=set(src1_pregs.values()) | set(src2_pregs.values()))
        dst_pregs = {start_vline + i: dst_pregs_list[i]
                     for i in range(len(dst_pregs_list))}
        return self.rename(
            src_pregs=src1_pregs,
            src2_pregs=src2_pregs,
            dst_pregs=dst_pregs,
        )

    async def execute(self, kamlet) -> None:
        vrange = self._vline_range(kamlet)
        if vrange is None:
            kamlet.monitor.finalize_kinstr_exec(
                self.instr_ident, kamlet.min_x, kamlet.min_y)
            return
        start_vline, end_vline = vrange
        r = self.renamed
        wb = kamlet.params.word_bytes
        j_in_l = kamlet.params.j_in_l
        bits_per_jamlet_vline = wb * 8
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            # Per-vline wb-byte active mask: 1 for each bit whose element is in
            # [start_index, n_elements) and maps to this jamlet.
            active_masks = {v: bytearray(wb)
                            for v in range(start_vline, end_vline + 1)}
            vw_index = addresses.k_indices_to_vw_index(
                kamlet.params, self.word_order, kamlet.k_index, j_in_k_index)
            low = start_vline * bits_per_jamlet_vline
            high = (end_vline + 1) * bits_per_jamlet_vline
            for element_in_jamlet in range(low, high):
                e = vw_index + j_in_l * element_in_jamlet
                if e < self.start_index or e >= self.n_elements:
                    continue
                vline_idx = element_in_jamlet // bits_per_jamlet_vline
                bit_in_jvec = element_in_jamlet % bits_per_jamlet_vline
                byte_idx = bit_in_jvec // 8
                bit_in_byte = bit_in_jvec % 8
                active_masks[vline_idx][byte_idx] |= (1 << bit_in_byte)

            for vline_idx in range(start_vline, end_vline + 1):
                src1_base = r.src_pregs[vline_idx] * wb
                src2_base = r.src2_pregs[vline_idx] * wb
                dst_preg = r.dst_pregs[vline_idx]
                dst_base = dst_preg * wb
                for byte_offset in range(wb):
                    active = active_masks[vline_idx][byte_offset]
                    if active == 0:
                        continue
                    s1 = jamlet.rf_slice[src1_base + byte_offset]
                    s2 = jamlet.rf_slice[src2_base + byte_offset]
                    op_byte = _vmlogic_eval(self.op, s1, s2)
                    old = jamlet.rf_slice[dst_base + byte_offset]
                    new_byte = (op_byte & active) | (old & (~active & 0xff))
                    jamlet.write_vreg(dst_preg, byte_offset, bytes([new_byte]),
                                      span_id=span_id)
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

    async def admit(self, kamlet) -> 'VBroadcastOp | None':
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        elements_in_vline = bits_in_vline // self.element_width

        # Rename: lookup mask phys before allocating dst phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        exclude = {mask_preg} if mask_preg is not None else set()
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline,
            mask_present=self.mask_reg is not None,
            exclude_reuse=exclude)
        return self.rename(
            dst_pregs={v: dst_pregs[v] for v in range(n_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        mask_preg = r.mask_preg

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                dst_preg = r.dst_pregs[vline_index]
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
                        jamlet.write_vreg(dst_preg, byte_offset, result_bytes,
                                          span_id=span_id)
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

    async def admit(self, kamlet) -> 'VidOp | None':
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        elements_in_vline = bits_in_vline // self.element_width

        # Rename: lookup mask phys before allocating dst phys.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        exclude = {mask_preg} if mask_preg is not None else set()
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=elements_in_vline,
            mask_present=self.mask_reg is not None,
            exclude_reuse=exclude)
        return self.rename(
            dst_pregs={v: dst_pregs[v] for v in range(n_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        params = kamlet.params
        bits_in_vline = params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        eb = self.element_width // 8
        wb = params.word_bytes
        start_index = 0
        elements_in_vline = params.vline_bytes * 8 // self.element_width
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            vw_index = addresses.k_indices_to_vw_index(
                params, self.word_order, kamlet.k_index, j_in_k_index)
            for vline_index in range(n_vlines):
                dst_preg = r.dst_pregs[vline_index]
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    element_index = (vline_index * elements_in_vline +
                                     index_in_j * params.j_in_l + vw_index)
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        r.mask_preg, vline_index, j_in_k_index, index_in_j
                    )
                    if valid_element and mask_bit:
                        result_bytes = element_index.to_bytes(eb, byteorder='little', signed=False)
                        jamlet.write_vreg(dst_preg, byte_offset, result_bytes,
                                          span_id=span_id,
                                          event_details={'element_index': element_index})
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
    invert_mask: bool = False

    async def admit(self, kamlet) -> 'VUnaryOvOp | None':
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        n_src_vlines = (self.n_elements * self.src_ew + bits_in_vline - 1) // bits_in_vline
        dst_elements_in_vline = bits_in_vline // self.dst_ew

        # Rename: lookup src physes (and mask) before allocating dst physes.
        src_pregs = [kamlet.r(self.src + i) for i in range(n_src_vlines)]
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        exclude = set(src_pregs)
        if mask_preg is not None:
            exclude.add(mask_preg)
        dst_pregs = await kamlet.alloc_dst_pregs(
            base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
            start_index=0, n_elements=self.n_elements,
            elements_in_vline=dst_elements_in_vline,
            mask_present=self.mask_reg is not None,
            exclude_reuse=exclude)
        return self.rename(
            src_pregs={v: src_pregs[v] for v in range(n_src_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_dst_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline

        params = kamlet.params
        src_eb = self.src_ew // 8
        dst_eb = self.dst_ew // 8
        wb = params.word_bytes
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        dst_elements_per_word = wb // dst_eb
        src_elements_per_word = wb // src_eb
        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_dst_vlines):
                dst_preg = r.dst_pregs[vline_index]
                for index_in_j in range(dst_elements_per_word):
                    valid_element, mask_bit = kamlet.get_is_active(
                        0, self.n_elements, self.dst_ew, self.word_order,
                        r.mask_preg, vline_index, j_in_k_index, index_in_j)
                    if self.invert_mask:
                        mask_bit = 1 - mask_bit
                    if not (valid_element and mask_bit):
                        continue
                    # Element index within this jamlet
                    dst_elem = vline_index * dst_elements_per_word + index_in_j
                    # Same element in the source layout
                    src_vline = dst_elem // src_elements_per_word
                    src_idx = dst_elem % src_elements_per_word
                    src_base = r.src_pregs[src_vline] * wb
                    dst_byte_in_word = index_in_j * dst_eb
                    src_byte = src_base + src_idx * src_eb
                    src_bytes = jamlet.rf_slice[src_byte:src_byte + src_eb]
                    result = self._convert(src_bytes, src_eb, dst_eb)
                    jamlet.write_vreg(dst_preg, dst_byte_in_word, result,
                                      span_id=span_id)
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

    async def admit(self, kamlet) -> 'ReadRegWord | None':
        src_preg = kamlet.r(self.src)
        return self.rename(src_pregs={0: src_preg})

    async def execute(self, kamlet) -> None:
        r = self.renamed
        src_preg = r.src_pregs[0]
        rf_ident = kamlet.rf_info.start(
            read_regs=r.read_pregs, write_regs=r.write_pregs)
        jamlet = kamlet.jamlets[self.j_in_k_index]
        wb = kamlet.params.word_bytes
        byte_offset = src_preg * wb
        word = int.from_bytes(
            jamlet.rf_slice[byte_offset:byte_offset + wb], 'little',
        )
        kamlet.rf_info.finish(
            rf_ident, read_regs=r.read_pregs, write_regs=r.write_pregs)
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
    # When mask_reg is not None, check bit `mask_index` of that jamlet's word
    # in the mask register; skip the write when the bit is 0.
    mask_reg: int | None = None
    mask_index: int = 0

    async def admit(self, kamlet) -> 'WriteRegElement | None':
        vw_index = self.element_index % kamlet.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            kamlet.params, self.ordering.word_order, vw_index)
        assert k_index == kamlet.k_index
        # Single-element patch: the unwritten elements must keep their old
        # values, so this is semantically RMW. Use rw() to reuse the existing
        # phys rather than rotating in a fresh (uninitialised) one.
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        dst_preg = kamlet.rw(self.dst)
        return self.rename(dst_pregs={0: dst_preg}, mask_preg=mask_preg)

    async def execute(self, kamlet) -> None:
        r = self.renamed
        vw_index = self.element_index % kamlet.params.j_in_l
        k_index, j_in_k_index = addresses.vw_index_to_k_indices(
            kamlet.params, self.ordering.word_order, vw_index)
        dst_preg = r.dst_pregs[0]
        jamlet = kamlet.jamlets[j_in_k_index]
        if r.mask_preg is not None:
            wb = kamlet.params.word_bytes
            mask_word = int.from_bytes(
                jamlet.rf_slice[r.mask_preg * wb: (r.mask_preg + 1) * wb],
                byteorder='little')
            mask_bit = (mask_word >> self.mask_index) & 1
            if not mask_bit:
                kamlet.monitor.finalize_kinstr_exec(
                    self.instr_ident, kamlet.min_x, kamlet.min_y,
                )
                return
        element_in_jamlet = self.element_index // kamlet.params.j_in_l
        eb = self.element_width // 8
        offset_in_word = element_in_jamlet * eb
        value_bytes = self.value.to_bytes(eb, byteorder='little', signed=True)
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)
        jamlet.write_vreg(dst_preg, offset_in_word, value_bytes, span_id=span_id,
                          event_details={'element_index': self.element_index})
        kamlet.monitor.finalize_kinstr_exec(
            self.instr_ident, kamlet.min_x, kamlet.min_y,
        )


FLOAT_OPS = (
    VArithOp.FADD, VArithOp.FSUB, VArithOp.FRSUB,
    VArithOp.FMUL, VArithOp.FDIV, VArithOp.FRDIV,
    VArithOp.FMACC, VArithOp.FNMACC, VArithOp.FMADD, VArithOp.FNMADD,
    VArithOp.FMSAC, VArithOp.FNMSAC, VArithOp.FMSUB, VArithOp.FNMSUB,
    VArithOp.FMIN, VArithOp.FMAX,
    VArithOp.FSGNJ, VArithOp.FSGNJN, VArithOp.FSGNJX,
)
SGNJ_OPS = (VArithOp.FSGNJ, VArithOp.FSGNJN, VArithOp.FSGNJX)
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


def _compute_arith(op, src1_val, src2_val, acc_val, eb, shift_eb=None):
    """Compute the result of a vector arithmetic operation.

    src1_val: first source (vs1 for VV, scalar for VX)
    src2_val: second source (vs2)
    acc_val: accumulator value (vd, only used for ACCUM_OPS)
    eb: element width in bytes (only used for shift masking)
    shift_eb: byte width whose low lg2(8*shift_eb) bits define the shift
        mask. Defaults to eb. For narrowing shifts (vnsrl, vnsra) this is
        the source (2*SEW) width; for widening shifts (vwsll) this is the
        destination width.
    """
    if shift_eb is None:
        shift_eb = eb
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
        return src2_val << (src1_val & (shift_eb * 8 - 1))
    elif op == VArithOp.SRL:
        return src2_val >> (src1_val & (shift_eb * 8 - 1))
    elif op == VArithOp.SRA:
        return src2_val >> (src1_val & (shift_eb * 8 - 1))
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
    elif op in SGNJ_OPS:
        # RVV vfsgnj{,n,x}.vv vd, vs2, vs1: magnitude from vs2 (=src2), sign
        # from vs1 (=src1) / negated / XORed with src2 sign. Bit-level, so
        # round-trip through the int view of the float to manipulate the
        # sign bit directly.
        int_fmt = {8: '<Q', 4: '<I', 2: '<H'}[eb]
        float_fmt = {8: '<d', 4: '<f', 2: '<e'}[eb]
        width = eb * 8
        sign_bit = 1 << (width - 1)
        b1 = struct.unpack(int_fmt, struct.pack(float_fmt, src1_val))[0]
        b2 = struct.unpack(int_fmt, struct.pack(float_fmt, src2_val))[0]
        magnitude = b2 & (sign_bit - 1)
        if op is VArithOp.FSGNJ:
            new_sign = b1 & sign_bit
        elif op is VArithOp.FSGNJN:
            new_sign = (b1 & sign_bit) ^ sign_bit
        elif op is VArithOp.FSGNJX:
            new_sign = (b1 ^ b2) & sign_bit
        else:
            raise AssertionError(f"unhandled sign-inject op: {op}")
        return struct.unpack(float_fmt, struct.pack(int_fmt, magnitude | new_sign))[0]
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

    async def admit(self, kamlet) -> 'VArithVvOp | None':
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
            exclude = set(src1_pregs) | set(src2_pregs)
            if mask_preg is not None:
                exclude.add(mask_preg)
            dst_pregs = await kamlet.alloc_dst_pregs(
                base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
                start_index=0, n_elements=self.n_elements,
                elements_in_vline=elements_in_vline,
                mask_present=self.mask_reg is not None,
                exclude_reuse=exclude)
        return self.rename(
            src_pregs={v: src1_pregs[v] for v in range(n_vlines)},
            src2_pregs={v: src2_pregs[v] for v in range(n_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes
        start_index = 0
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                src1_base = r.src_pregs[vline_index] * wb
                src2_base = r.src2_pregs[vline_index] * wb
                dst_preg = r.dst_pregs[vline_index]
                dst_base = dst_preg * wb
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        r.mask_preg, vline_index, j_in_k_index, index_in_j
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
                        jamlet.write_vreg(dst_preg, byte_offset, struct.pack(fmt, result),
                                          span_id=span_id)
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

    async def admit(self, kamlet) -> 'VArithVxOp | None':
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
            exclude = set(src2_pregs)
            if mask_preg is not None:
                exclude.add(mask_preg)
            dst_pregs = await kamlet.alloc_dst_pregs(
                base_arch=self.dst, start_vline=0, end_vline=n_vlines - 1,
                start_index=0, n_elements=self.n_elements,
                elements_in_vline=elements_in_vline,
                mask_present=self.mask_reg is not None,
                exclude_reuse=exclude)
        return self.rename(
            src2_pregs={v: src2_pregs[v] for v in range(n_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_vlines = (self.n_elements * self.element_width + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS

        eb = self.element_width // 8
        wb = kamlet.params.word_bytes

        fmt = _arith_fmt(self.op, eb)
        scalar_val = struct.unpack(fmt, self.scalar_bytes[:eb])[0]
        start_index = 0
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_vlines):
                src2_base = r.src2_pregs[vline_index] * wb
                dst_preg = r.dst_pregs[vline_index]
                dst_base = dst_preg * wb
                for index_in_j in range(wb // eb):
                    byte_offset = index_in_j * eb
                    valid_element, mask_bit = kamlet.get_is_active(
                        start_index, self.n_elements, self.element_width, self.word_order,
                        r.mask_preg, vline_index, j_in_k_index, index_in_j)
                    if valid_element and mask_bit:
                        src2_bytes = jamlet.rf_slice[src2_base + byte_offset:src2_base + byte_offset + eb]
                        src2_val = struct.unpack(fmt, src2_bytes)[0]
                        acc_val = None
                        if is_accum:
                            acc_bytes = jamlet.rf_slice[dst_base + byte_offset:dst_base + byte_offset + eb]
                            acc_val = struct.unpack(fmt, acc_bytes)[0]
                        result = _compute_arith(self.op, scalar_val, src2_val, acc_val, eb)
                        result = _arith_truncate_int(self.op, result, eb)
                        jamlet.write_vreg(dst_preg, byte_offset, struct.pack(fmt, result),
                                          span_id=span_id)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


_SHIFT_OPS = (VArithOp.SLL, VArithOp.SRL, VArithOp.SRA)


def _ov_int_fmt(eb: int, signed: bool) -> str:
    if signed:
        return {8: '<q', 4: '<i', 2: '<h', 1: '<b'}[eb]
    return {8: '<Q', 4: '<I', 2: '<H', 1: '<B'}[eb]


def _ov_arith_fmt(op, eb: int, signed: bool) -> str:
    """Return struct format for an Ov operand with explicit signedness."""
    if op in FLOAT_OPS:
        return {8: 'd', 4: 'f', 2: 'e'}[eb]
    return _ov_int_fmt(eb, signed)


def _ov_dst_signed(op, src1_signed: bool, src2_signed: bool) -> bool:
    """Destination signedness for the widening/narrowing Ov classes.

    Float ops: signedness is irrelevant (caller picks the float fmt).
    Integer ops: result is unsigned only if all integer sources are unsigned;
    otherwise signed. This matches the spec for the widening add/sub/mul/mac
    family (vwaddu/vwmulu/vwmaccu unsigned; everything mixed or signed → signed)
    and for narrowing shifts (vnsrl unsigned, vnsra signed).
    """
    if op in FLOAT_OPS:
        return False
    return not (not src1_signed and not src2_signed)


def _ov_truncate_int(op, result, dst_eb: int, dst_signed: bool):
    if op in FLOAT_OPS:
        return result
    mask = (1 << (dst_eb * 8)) - 1
    result = result & mask
    if dst_signed and result >= (1 << (dst_eb * 8 - 1)):
        result -= (1 << (dst_eb * 8))
    return result


@dataclass
class VArithVvOvOp(KInstr):
    """Binary vector arithmetic with per-operand widths and signedness.

    Covers the widening (vwadd/vwsub/vwmul/vwmac/vfw*) and narrowing (vnsrl,
    vnsra) families. ``src{1,2}_ew`` and ``dst_ew`` are independent; per-source
    signedness drives unpack format and the destination signedness convention.
    """
    op: VArithOp
    dst: int
    src1: int
    src2: int
    mask_reg: int | None
    n_elements: int
    src1_ew: int
    src2_ew: int
    dst_ew: int
    src1_signed: bool
    src2_signed: bool
    word_order: addresses.WordOrder
    instr_ident: int
    is_float: bool = False

    async def admit(self, kamlet) -> 'VArithVvOvOp | None':
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_src1_vlines = (self.n_elements * self.src1_ew + bits_in_vline - 1) // bits_in_vline
        n_src2_vlines = (self.n_elements * self.src2_ew + bits_in_vline - 1) // bits_in_vline
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS
        dst_elements_in_vline = bits_in_vline // self.dst_ew

        src1_pregs = [kamlet.r(self.src1 + i) for i in range(n_src1_vlines)]
        src2_pregs = [kamlet.r(self.src2 + i) for i in range(n_src2_vlines)]
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        if is_accum:
            dst_pregs = [kamlet.rw(self.dst + i) for i in range(n_dst_vlines)]
        else:
            exclude = set(src1_pregs) | set(src2_pregs)
            if mask_preg is not None:
                exclude.add(mask_preg)
            dst_pregs = await kamlet.alloc_dst_pregs(
                base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
                start_index=0, n_elements=self.n_elements,
                elements_in_vline=dst_elements_in_vline,
                mask_present=self.mask_reg is not None,
                exclude_reuse=exclude)
        return self.rename(
            src_pregs={v: src1_pregs[v] for v in range(n_src1_vlines)},
            src2_pregs={v: src2_pregs[v] for v in range(n_src2_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_dst_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS

        src1_eb = self.src1_ew // 8
        src2_eb = self.src2_ew // 8
        dst_eb = self.dst_ew // 8
        wb = kamlet.params.word_bytes

        dst_elements_per_word = wb // dst_eb
        src1_elements_per_word = wb // src1_eb
        src2_elements_per_word = wb // src2_eb

        dst_signed = _ov_dst_signed(self.op, self.src1_signed, self.src2_signed)
        src1_fmt = _ov_arith_fmt(self.op, src1_eb, self.src1_signed)
        src2_fmt = _ov_arith_fmt(self.op, src2_eb, self.src2_signed)
        dst_fmt = _ov_arith_fmt(self.op, dst_eb, dst_signed)
        # Narrowing shifts mask the count by lg2(2*SEW); src2_eb is 2*SEW.
        shift_eb = src2_eb if self.op in _SHIFT_OPS else dst_eb
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_dst_vlines):
                dst_preg = r.dst_pregs[vline_index]
                dst_base = dst_preg * wb
                for index_in_j in range(dst_elements_per_word):
                    valid_element, mask_bit = kamlet.get_is_active(
                        0, self.n_elements, self.dst_ew, self.word_order,
                        r.mask_preg, vline_index, j_in_k_index, index_in_j)
                    if not (valid_element and mask_bit):
                        continue
                    dst_elem = vline_index * dst_elements_per_word + index_in_j
                    src1_vline = dst_elem // src1_elements_per_word
                    src1_idx = dst_elem % src1_elements_per_word
                    src2_vline = dst_elem // src2_elements_per_word
                    src2_idx = dst_elem % src2_elements_per_word
                    src1_base = r.src_pregs[src1_vline] * wb
                    src2_base = r.src2_pregs[src2_vline] * wb
                    src1_byte = src1_base + src1_idx * src1_eb
                    src2_byte = src2_base + src2_idx * src2_eb
                    dst_byte_in_word = index_in_j * dst_eb
                    dst_byte = dst_base + dst_byte_in_word
                    src1_bytes = jamlet.rf_slice[src1_byte:src1_byte + src1_eb]
                    src2_bytes = jamlet.rf_slice[src2_byte:src2_byte + src2_eb]
                    src1_val = struct.unpack(src1_fmt, src1_bytes)[0]
                    src2_val = struct.unpack(src2_fmt, src2_bytes)[0]
                    acc_val = None
                    if is_accum:
                        acc_bytes = jamlet.rf_slice[dst_byte:dst_byte + dst_eb]
                        acc_val = struct.unpack(dst_fmt, acc_bytes)[0]
                    result = _compute_arith(
                        self.op, src1_val, src2_val, acc_val, dst_eb,
                        shift_eb=shift_eb,
                    )
                    result = _ov_truncate_int(self.op, result, dst_eb, dst_signed)
                    jamlet.write_vreg(dst_preg, dst_byte_in_word,
                                      struct.pack(dst_fmt, result),
                                      span_id=span_id)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)


@dataclass
class VArithVxOvOp(KInstr):
    """Vector-scalar form of VArithVvOvOp. ``scalar_bytes`` carries the rs1
    payload (or the immediate, encoded the same way as for VArithVxOp).
    """
    op: VArithOp
    dst: int
    scalar_bytes: bytes
    src2: int
    mask_reg: int | None
    n_elements: int
    scalar_ew: int
    src2_ew: int
    dst_ew: int
    scalar_signed: bool
    src2_signed: bool
    word_order: addresses.WordOrder
    instr_ident: int
    is_float: bool = False

    async def admit(self, kamlet) -> 'VArithVxOvOp | None':
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_src2_vlines = (self.n_elements * self.src2_ew + bits_in_vline - 1) // bits_in_vline
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS
        dst_elements_in_vline = bits_in_vline // self.dst_ew

        src2_pregs = [kamlet.r(self.src2 + i) for i in range(n_src2_vlines)]
        mask_preg = kamlet.r(self.mask_reg) if self.mask_reg is not None else None
        if is_accum:
            dst_pregs = [kamlet.rw(self.dst + i) for i in range(n_dst_vlines)]
        else:
            exclude = set(src2_pregs)
            if mask_preg is not None:
                exclude.add(mask_preg)
            dst_pregs = await kamlet.alloc_dst_pregs(
                base_arch=self.dst, start_vline=0, end_vline=n_dst_vlines - 1,
                start_index=0, n_elements=self.n_elements,
                elements_in_vline=dst_elements_in_vline,
                mask_present=self.mask_reg is not None,
                exclude_reuse=exclude)
        return self.rename(
            src2_pregs={v: src2_pregs[v] for v in range(n_src2_vlines)},
            dst_pregs={v: dst_pregs[v] for v in range(n_dst_vlines)},
            mask_preg=mask_preg,
        )

    async def execute(self, kamlet) -> None:
        r = self.renamed
        bits_in_vline = kamlet.params.vline_bytes * 8
        n_dst_vlines = (self.n_elements * self.dst_ew + bits_in_vline - 1) // bits_in_vline
        is_accum = self.op in ACCUM_OPS

        scalar_eb = self.scalar_ew // 8
        src2_eb = self.src2_ew // 8
        dst_eb = self.dst_ew // 8
        wb = kamlet.params.word_bytes

        dst_elements_per_word = wb // dst_eb
        src2_elements_per_word = wb // src2_eb

        dst_signed = _ov_dst_signed(self.op, self.scalar_signed, self.src2_signed)
        scalar_fmt = _ov_arith_fmt(self.op, scalar_eb, self.scalar_signed)
        src2_fmt = _ov_arith_fmt(self.op, src2_eb, self.src2_signed)
        dst_fmt = _ov_arith_fmt(self.op, dst_eb, dst_signed)
        scalar_val = struct.unpack(scalar_fmt, self.scalar_bytes[:scalar_eb])[0]
        shift_eb = src2_eb if self.op in _SHIFT_OPS else dst_eb
        span_id = kamlet.monitor.get_kinstr_exec_span_id(
            self.instr_ident, kamlet.min_x, kamlet.min_y)

        for j_in_k_index, jamlet in enumerate(kamlet.jamlets):
            for vline_index in range(n_dst_vlines):
                dst_preg = r.dst_pregs[vline_index]
                dst_base = dst_preg * wb
                for index_in_j in range(dst_elements_per_word):
                    valid_element, mask_bit = kamlet.get_is_active(
                        0, self.n_elements, self.dst_ew, self.word_order,
                        r.mask_preg, vline_index, j_in_k_index, index_in_j)
                    if not (valid_element and mask_bit):
                        continue
                    dst_elem = vline_index * dst_elements_per_word + index_in_j
                    src2_vline = dst_elem // src2_elements_per_word
                    src2_idx = dst_elem % src2_elements_per_word
                    src2_base = r.src2_pregs[src2_vline] * wb
                    src2_byte = src2_base + src2_idx * src2_eb
                    dst_byte_in_word = index_in_j * dst_eb
                    dst_byte = dst_base + dst_byte_in_word
                    src2_bytes = jamlet.rf_slice[src2_byte:src2_byte + src2_eb]
                    src2_val = struct.unpack(src2_fmt, src2_bytes)[0]
                    acc_val = None
                    if is_accum:
                        acc_bytes = jamlet.rf_slice[dst_byte:dst_byte + dst_eb]
                        acc_val = struct.unpack(dst_fmt, acc_bytes)[0]
                    result = _compute_arith(
                        self.op, scalar_val, src2_val, acc_val, dst_eb,
                        shift_eb=shift_eb,
                    )
                    result = _ov_truncate_int(self.op, result, dst_eb, dst_signed)
                    jamlet.write_vreg(dst_preg, dst_byte_in_word,
                                      struct.pack(dst_fmt, result),
                                      span_id=span_id)
        kamlet.monitor.finalize_kinstr_exec(self.instr_ident, kamlet.min_x, kamlet.min_y)



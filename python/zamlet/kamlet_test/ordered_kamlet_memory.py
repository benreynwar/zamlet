"""Logical memory model for ordered kamlet cache-line traffic."""

import logging
from dataclasses import dataclass

from zamlet import utils
from zamlet.addresses import Ordering
from zamlet.cocotb.axi_memory import Axi4MemoryBase, Axi4Signals
from zamlet.kamlet_test.tag_table_driver import TagState
from zamlet.lane_order import k_indices_to_vw_index
from zamlet.params import ZamletParams


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StripeMapping:
    logical_stripe_addr: int
    ordering: Ordering


@dataclass(frozen=True)
class ReverseStripeMapping:
    physical_stripe_addr: int
    ordering: Ordering


@dataclass(frozen=True)
class CacheSlotSnapshot:
    slot: int
    state: int
    state_name: str
    tag: int


class OrderedKamletMemory:
    """Stores logical bytes while accepting physical kamlet cache-line words."""

    def __init__(self, params: ZamletParams):
        self.params = params
        self.memory: dict[int, int] = {}
        self.stripe_ordering: dict[int, StripeMapping] = {}
        self.reverse_stripe_ordering: dict[int, ReverseStripeMapping] = {}

    def map_stripe(
        self, physical_stripe_addr: int, logical_stripe_addr: int, ordering: Ordering,
    ) -> None:
        mapping = StripeMapping(logical_stripe_addr, ordering)
        reverse_mapping = ReverseStripeMapping(physical_stripe_addr, ordering)
        if physical_stripe_addr in self.stripe_ordering:
            assert self.stripe_ordering[physical_stripe_addr] == mapping
        if logical_stripe_addr in self.reverse_stripe_ordering:
            assert self.reverse_stripe_ordering[logical_stripe_addr] == reverse_mapping
        self.stripe_ordering[physical_stripe_addr] = mapping
        self.reverse_stripe_ordering[logical_stripe_addr] = reverse_mapping

    def map_cache_line(
        self,
        physical_cache_line_addr: int,
        logical_cache_line_addr: int,
        ordering: Ordering,
    ) -> None:
        for word_index in range(self.params.cache_slot_words_per_jamlet):
            self.map_stripe(
                self._cache_line_stripe_addr(physical_cache_line_addr, word_index),
                self._cache_line_stripe_addr(logical_cache_line_addr, word_index),
                ordering,
            )

    def translate_logical_stripe(
        self, logical_stripe_addr: int,
    ) -> ReverseStripeMapping:
        assert logical_stripe_addr in self.reverse_stripe_ordering, (
            f'unmapped logical stripe 0x{logical_stripe_addr:x}')
        return self.reverse_stripe_ordering[logical_stripe_addr]

    def write_logical_bytes(self, logical_addr: int, data: bytes) -> None:
        for offset, byte in enumerate(data):
            self.memory[logical_addr + offset] = byte

    def read_logical_bytes(self, logical_addr: int, n_bytes: int) -> bytes:
        return bytes(
            self.memory.get(logical_addr + offset, 0)
            for offset in range(n_bytes)
        )

    def write_kamlet_cache_line(
        self, k_index: int, physical_cache_line_addr: int, words: list[int],
    ) -> None:
        self._check_cache_line_words(k_index, words)
        for word_index in range(self.params.cache_slot_words_per_jamlet):
            physical_stripe_addr = self._cache_line_stripe_addr(
                physical_cache_line_addr, word_index)
            for j_in_k_index in range(self.params.j_in_k):
                word = words[word_index * self.params.j_in_k + j_in_k_index]
                for byte_offset in range(self.params.word_bytes):
                    logical_addr = self._logical_addr_for_cache_byte(
                        k_index, j_in_k_index, physical_stripe_addr, byte_offset)
                    self.memory[logical_addr] = (word >> (8 * byte_offset)) & 0xff

    def read_kamlet_cache_line(
        self, k_index: int, physical_cache_line_addr: int,
    ) -> list[int]:
        self._check_k_index(k_index)
        words = []
        for word_index in range(self.params.cache_slot_words_per_jamlet):
            physical_stripe_addr = self._cache_line_stripe_addr(
                physical_cache_line_addr, word_index)
            for j_in_k_index in range(self.params.j_in_k):
                word = 0
                for byte_offset in range(self.params.word_bytes):
                    logical_addr = self._logical_addr_for_cache_byte(
                        k_index, j_in_k_index, physical_stripe_addr, byte_offset)
                    word |= self.memory.get(logical_addr, 0) << (8 * byte_offset)
                words.append(word)
        return words

    def base_addr_for_cache_line(
        self, physical_cache_line_addr: int, word_index: int = 0,
    ) -> int:
        assert 0 <= word_index < self.params.cache_slot_words_per_jamlet
        return (
            physical_cache_line_addr
            << (self.params.log2_cache_slot_words_per_jamlet + self.params.log2_j_in_l)
        ) | (word_index << self.params.log2_j_in_k)

    def read_lamlet_cache_line_from_dut(
        self, dut, logical_cache_line_addr: int,
    ) -> list[int | None]:
        params = self.params
        result: list[int | None] = [
            None for _ in range(
                params.cache_slot_words_per_jamlet * params.stripe_bytes)
        ]
        for physical_cache_line_addr, logical_base in self._mapped_cache_lines():
            if logical_base != logical_cache_line_addr:
                continue
            for k_index in range(params.k_in_l):
                slot = self._present_cache_slot(dut, k_index, physical_cache_line_addr)
                if slot is None:
                    continue
                for word_index in range(params.cache_slot_words_per_jamlet):
                    physical_stripe_addr = self._cache_line_stripe_addr(
                        physical_cache_line_addr, word_index)
                    for j_in_k_index in range(params.j_in_k):
                        word = self._read_sram_word(
                            dut, k_index, j_in_k_index, slot, word_index)
                        for byte_offset in range(params.word_bytes):
                            logical_addr = self._logical_addr_for_cache_byte(
                                k_index, j_in_k_index, physical_stripe_addr, byte_offset)
                            logical_offset = (
                                logical_addr
                                - logical_cache_line_addr
                                * params.cache_slot_words_per_jamlet
                                * params.stripe_bytes
                            )
                            result[logical_offset] = (
                                word >> (8 * byte_offset)
                            ) & 0xff
        return result

    def read_lamlet_cache_line_coherent_from_dut(
        self, dut, logical_cache_line_addr: int,
    ) -> list[int]:
        params = self.params
        line_bytes = params.cache_slot_words_per_jamlet * params.stripe_bytes
        result = list(self.read_logical_bytes(
            logical_cache_line_addr * line_bytes,
            line_bytes,
        ))
        cache_result = self.read_lamlet_cache_line_from_dut(
            dut, logical_cache_line_addr)
        for index, value in enumerate(cache_result):
            if value is not None:
                result[index] = value
        return result

    def cache_slot_snapshots(self, dut, k_index: int) -> list[CacheSlotSnapshot]:
        tag_table = self._kamlet(dut, k_index).cacheEngine.tagTable
        snapshots = []
        for slot in range(self.params.n_cache_slots):
            state = int(getattr(tag_table, f'state_{slot}').value)
            tag = int(getattr(tag_table, f'tag_{slot}').value)
            snapshots.append(CacheSlotSnapshot(
                slot=slot,
                state=state,
                state_name=self._tag_state_name(state),
                tag=tag,
            ))
        return snapshots

    def log_cache_line_debug(self, dut, logical_cache_line_addr: int) -> None:
        mapped_lines = self._mapped_cache_lines()
        logger.debug(
            'cache-line probe logical=0x%x mapped=[%s]',
            logical_cache_line_addr,
            ', '.join(
                f'physical=0x{physical:x}->logical=0x{logical:x}'
                for physical, logical in mapped_lines
            ),
        )
        for physical_cache_line_addr, logical_base in mapped_lines:
            if logical_base != logical_cache_line_addr:
                continue
            for k_index in range(self.params.k_in_l):
                present_slot = self._present_cache_slot(
                    dut, k_index, physical_cache_line_addr)
                slots = ', '.join(
                    f'{slot.slot}:{slot.state_name}:tag=0x{slot.tag:x}'
                    for slot in self.cache_slot_snapshots(dut, k_index)
                )
                logger.debug(
                    'cache-line probe k=%d physical=0x%x present_slot=%s slots=[%s]',
                    k_index,
                    physical_cache_line_addr,
                    present_slot,
                    slots,
                )

    def _logical_addr_for_cache_byte(
        self,
        k_index: int,
        j_in_k_index: int,
        physical_stripe_addr: int,
        byte_offset: int,
    ) -> int:
        params = self.params
        mapping = self.stripe_ordering[physical_stripe_addr]
        ordering = mapping.ordering

        # This is the same byte factoring used by the J2J mapping model:
        # [element bit, logical lane, element-in-word]. The lane order maps
        # the physical kamlet/jamlet position back to the logical lane.
        assert 8 <= ordering.ew <= params.word_width
        assert ordering.ew % 8 == 0
        assert params.word_width % ordering.ew == 0
        logical_vw = k_indices_to_vw_index(
            params, ordering.word_order, k_index, j_in_k_index)
        logical_bit_offset = utils.join_by_factors(
            [
                (byte_offset * 8) % ordering.ew,
                logical_vw,
                (byte_offset * 8) // ordering.ew,
            ],
            [ordering.ew, params.j_in_l, params.word_width // ordering.ew],
        )
        assert logical_bit_offset % 8 == 0
        return (
            mapping.logical_stripe_addr * params.stripe_bytes
            + logical_bit_offset // 8
        )

    def _cache_line_stripe_addr(self, cache_line_addr: int, word_index: int) -> int:
        assert 0 <= word_index < self.params.cache_slot_words_per_jamlet
        return cache_line_addr * self.params.cache_slot_words_per_jamlet + word_index

    def _check_cache_line_words(self, k_index: int, words: list[int]) -> None:
        self._check_k_index(k_index)
        expected = self.params.cache_slot_words_per_jamlet * self.params.j_in_k
        assert len(words) == expected
        for word in words:
            assert 0 <= word < (1 << self.params.word_width)

    def _check_k_index(self, k_index: int) -> None:
        assert 0 <= k_index < self.params.k_in_l

    def _mapped_cache_lines(self) -> list[tuple[int, int]]:
        mapped = {}
        for physical_stripe_addr, mapping in self.stripe_ordering.items():
            physical_cache_line_addr = (
                physical_stripe_addr // self.params.cache_slot_words_per_jamlet)
            word_index = physical_stripe_addr % self.params.cache_slot_words_per_jamlet
            logical_cache_line_addr = (
                mapping.logical_stripe_addr // self.params.cache_slot_words_per_jamlet)
            assert mapping.logical_stripe_addr % self.params.cache_slot_words_per_jamlet == word_index
            if physical_cache_line_addr in mapped:
                assert mapped[physical_cache_line_addr] == logical_cache_line_addr
            mapped[physical_cache_line_addr] = logical_cache_line_addr
        return list(mapped.items())

    def _present_cache_slot(
        self, dut, k_index: int, physical_cache_line_addr: int,
    ) -> int | None:
        kamlet = self._kamlet(dut, k_index)
        tag_table = kamlet.cacheEngine.tagTable
        for slot in range(self.params.n_cache_slots):
            state = int(getattr(tag_table, f'state_{slot}').value)
            tag = int(getattr(tag_table, f'tag_{slot}').value)
            if (
                state in (TagState.PRESENT_CLEAN, TagState.PRESENT_DIRTY)
                and tag == physical_cache_line_addr
            ):
                return slot
        return None

    def _tag_state_name(self, state: int) -> str:
        try:
            return TagState(state).name
        except ValueError:
            return f'UNKNOWN_{state}'

    def _read_sram_word(
        self,
        dut,
        k_index: int,
        j_in_k_index: int,
        slot: int,
        word_index: int,
    ) -> int:
        jamlet = self._jamlet(dut, k_index, j_in_k_index)
        sram_index = slot * self.params.cache_slot_words_per_jamlet + word_index
        return int(getattr(jamlet.SramWrapper.Sram, f'mem_{sram_index}').value)

    def _kamlet(self, dut, k_index: int):
        kx = k_index % self.params.k_cols
        ky = k_index // self.params.k_cols
        return getattr(dut.mesh, f'kamlets_{kx}_{ky}')

    def _jamlet(self, dut, k_index: int, j_in_k_index: int):
        kamlet = self._kamlet(dut, k_index)
        jx = j_in_k_index % self.params.j_cols
        jy = j_in_k_index // self.params.j_cols
        return getattr(kamlet, f'jamlets_{jy}_{jx}')


class OrderedKamletAxiMemory(Axi4MemoryBase):
    """AXI responder that translates kamlet cache-line beats to logical memory."""

    def __init__(
        self,
        signals: Axi4Signals,
        clock,
        params: ZamletParams,
        memory: OrderedKamletMemory,
        k_index: int,
        aw_p_ready: float = 1.0,
        w_p_ready: float = 1.0,
        ar_p_ready: float = 1.0,
        seed: int = 0,
    ):
        super().__init__(signals, clock, aw_p_ready, w_p_ready, ar_p_ready, seed)
        self.params = params
        self.memory = memory
        self.k_index = k_index

    def handle_write(self, aw: dict, data: list[int]) -> None:
        self._check_burst(aw, data)
        logger.debug(
            'axi write k=%d physical_cache_line=0x%x beats=%d',
            self.k_index,
            aw['addr'],
            len(data),
        )
        self.memory.write_kamlet_cache_line(
            self.k_index,
            aw['addr'],
            self._unpack_beats(data),
        )

    def handle_read(self, ar: dict) -> list[int]:
        logger.debug(
            'axi read k=%d physical_cache_line=0x%x',
            self.k_index,
            ar['addr'],
        )
        words = self.memory.read_kamlet_cache_line(self.k_index, ar['addr'])
        data = self._pack_words(words)
        self._check_burst(ar, data)
        return data

    def _check_burst(self, info: dict, data: list[int]) -> None:
        beat_bytes = self.params.mem_beat_words * self.params.word_bytes
        assert info['size'] == (beat_bytes - 1).bit_length()
        assert len(data) == self.params.cache_slot_words // self.params.mem_beat_words
        assert info['len'] == len(data) - 1

    def _pack_words(self, words: list[int]) -> list[int]:
        assert len(words) == self.params.cache_slot_words
        beat_words = self.params.mem_beat_words
        data = []
        for beat_start in range(0, len(words), beat_words):
            beat = 0
            for word_index, word in enumerate(words[beat_start:beat_start + beat_words]):
                beat |= word << (word_index * self.params.word_width)
            data.append(beat)
        return data

    def _unpack_beats(self, data: list[int]) -> list[int]:
        word_mask = (1 << self.params.word_width) - 1
        words = []
        for beat in data:
            for word_index in range(self.params.mem_beat_words):
                words.append((beat >> (word_index * self.params.word_width)) & word_mask)
        return words

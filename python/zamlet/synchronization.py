"""
Lamlet-wide Synchronization Network

This module implements a dedicated synchronization network for tracking when events
have occurred across all kamlets in a lamlet. It supports optional minimum value
aggregation.

Network Architecture:
- Separate 9-bit wide bus network (not using the main router network)
- Direct connections to all 8 neighbors (N, S, E, W, NE, NW, SE, SW)
- No routing - packets only go to immediate neighbors

Bus Format (sync_bus_width bits per cycle):
- [data_width] = last_word (1 if this is the final word of packet)
- [data_width-1:0] = data word (where data_width = sync_bus_width - 1)

Packet Format (in data_width-bit words):
- Word 0: sync_ident (sync_ident_width bits, fits in one word)
- Words 1+: value (1-4 bytes packed little-endian) if present

Packet length determines whether value is present:
- Length 1 word: sync only, no value
- Length 2+ words: sync + value

Send Conditions:
- Cardinal N/S: Send when the opposite column is synchronized
  - Send N when S column (all kamlets below us in this column) is synced
  - Send S when N column (all kamlets above us in this column) is synced

- Cardinal E/W: Send when the opposite row is synchronized
  - Send E when W row (all kamlets left of us in this row) is synced
  - Send W when E row (all kamlets right of us in this row) is synced

- Diagonal: Send when opposite quadrant + adjacent column + adjacent row are all synced
  - Send NE when SW quadrant + S column + W row are synced
  - Send NW when SE quadrant + S column + E row are synced
  - Send SE when NW quadrant + N column + W row are synced
  - Send SW when NE quadrant + N column + E row are synced

A kamlet must have locally seen the event before sending any sync message.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Set, List, TYPE_CHECKING

from zamlet.params import ZamletParams
from zamlet.utils import Queue, uint_to_list_of_uints, list_of_uints_to_uint

if TYPE_CHECKING:
    from zamlet.kamlet.cache_table import CacheTable


logger = logging.getLogger(__name__)


class SyncDirection(Enum):
    """Eight directions for sync network (including diagonals)."""
    N = 0
    S = 1
    E = 2
    W = 3
    NE = 4
    NW = 5
    SE = 6
    SW = 7


class SyncAggOp(Enum):
    """Idempotent aggregation ops supported by the sync network.

    All operands are unsigned integers up to 32 bits wide. Signed variants
    (MIN/MAX) interpret values according to the declared width at the call
    site; the network itself only sees unsigned bits. None-valued
    participants are skipped (existing MIN-with-None semantics).
    """
    MIN = 0            # signed min, width-dependent
    MINU = 1           # unsigned min
    MAX = 2            # signed max, width-dependent
    MAXU = 3           # unsigned max
    AND = 4            # bitwise AND
    OR = 5             # bitwise OR
    MIN_PAIR = 6       # packed pair of unsigned mins (see below)


# MIN_PAIR layout: two unsigned sub-fields packed into the low 12 bits of a
# 16-bit value (2 sync-bus bytes). Low field = MIN_PAIR_LOW_WIDTH bits,
# high field = MIN_PAIR_HIGH_WIDTH bits starting at bit MIN_PAIR_LOW_WIDTH.
#
# The low field uses 0 as the "absent" sentinel (its valid range is
# [1, max_response_tags-1], so 0 is unused).
#
# The high field carries an IQ-slot distance in [1, n_iq-1] — d=0 (the
# current slot) is always excluded from participants' contributions. We
# store d-1 so stored values occupy [0, n_iq-2] and all-1's remains
# unused as the absent sentinel. Using a max-value sentinel lets MIN
# naturally ignore absent participants: real contributions are strictly
# smaller than the sentinel. With n_iq up to 8, stored range is [0, 6]
# and sentinel is 7 — all within 3 bits.
#
# The IdentQuery flow uses this to carry both the regular-ident distance
# (low, 9 bits for max_response_tags up to 512) and the IQ-slot distance
# (high, 3 bits for up to n_ident_query_slots = 8).
MIN_PAIR_LOW_WIDTH = 9
MIN_PAIR_HIGH_WIDTH = 3
MIN_PAIR_TOTAL_WIDTH = MIN_PAIR_LOW_WIDTH + MIN_PAIR_HIGH_WIDTH


def pack_min_pair(low: Optional[int], high: Optional[int]) -> int:
    """Pack two sub-field values into a MIN_PAIR word.

    Low field: None → 0 (absent sentinel); non-None must be > 0.
    High field: stored as d-1 for real distances
    """
    low_mask = (1 << MIN_PAIR_LOW_WIDTH) - 1
    high_mask = (1 << MIN_PAIR_HIGH_WIDTH) - 1
    if low is None:
        low_val = 0
    else:
        low_val = low
        assert low != 0
    assert 2 <= high <= high_mask+1, f'high must be in range 2 to {high_mask+1} but it is {high}'
    high_val = high - 1
    assert 0 <= low_val <= low_mask
    return low_val | (high_val << MIN_PAIR_LOW_WIDTH)


def unpack_min_pair(value: int) -> tuple:
    """Decode a MIN_PAIR word into (low, high).

    Low field: 0 returns None (absent sentinel). High field is always
    returned as stored+1, an integer in [1, 2**MIN_PAIR_HIGH_WIDTH].
    The sentinel (stored=all-1's) decodes to 2**MIN_PAIR_HIGH_WIDTH,
    a value callers can use uniformly: e.g. (slot_idx + high) % n_iq
    equals slot_idx for the sentinel (when n_iq divides
    2**MIN_PAIR_HIGH_WIDTH).
    """
    low_mask = (1 << MIN_PAIR_LOW_WIDTH) - 1
    high_mask = (1 << MIN_PAIR_HIGH_WIDTH) - 1
    low = value & low_mask
    high_stored = (value >> MIN_PAIR_LOW_WIDTH) & high_mask
    high = high_stored + 1
    return (low if low != 0 else None, high)


def _sign_extend(value: int, width: int) -> int:
    """Interpret the low `width` bits of value as signed."""
    mask = (1 << width) - 1
    v = value & mask
    sign_bit = 1 << (width - 1)
    if v & sign_bit:
        return v - (1 << width)
    return v


def aggregate_sync_values(
    op: SyncAggOp, values: List[int], width: int = 32,
) -> Optional[int]:
    """Aggregate a list of per-region unsigned values with op.

    None entries are skipped. Returns None if values is empty.
    `width` is the operand bit-width for signed MIN/MAX.
    """
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    if op == SyncAggOp.MIN:
        # Signed min according to declared width.
        return min(filtered, key=lambda v: _sign_extend(v, width))
    if op == SyncAggOp.MINU:
        return min(filtered)
    if op == SyncAggOp.MAX:
        return max(filtered, key=lambda v: _sign_extend(v, width))
    if op == SyncAggOp.MAXU:
        return max(filtered)
    if op == SyncAggOp.AND:
        result = filtered[0]
        for v in filtered[1:]:
            result &= v
        return result
    if op == SyncAggOp.OR:
        result = 0
        for v in filtered:
            result |= v
        return result
    if op == SyncAggOp.MIN_PAIR:
        low_mask = (1 << MIN_PAIR_LOW_WIDTH) - 1
        high_mask = (1 << MIN_PAIR_HIGH_WIDTH) - 1
        lows = [v & low_mask for v in filtered if (v & low_mask) != 0]
        # High field uses all-1's as the absent sentinel, so we take a
        # plain min — real contributions (stored as d-1) are strictly
        # less than the sentinel and naturally win. When every
        # participant is absent the min equals the sentinel.
        highs = [(v >> MIN_PAIR_LOW_WIDTH) & high_mask for v in filtered]
        low_min = min(lows) if lows else 0
        high_min = min(highs) if highs else high_mask
        return low_min | (high_min << MIN_PAIR_LOW_WIDTH)
    raise AssertionError(f"unknown SyncAggOp {op}")


class WaitingItemSyncState(Enum):
    """Synchronization state for waiting items that require lamlet-wide sync."""
    NOT_STARTED = 0
    IN_PROGRESS = 1
    COMPLETE = 2


# Requirements for sending in each direction
# For cardinal directions: just need the opposite column/row synced
# For diagonal directions: need opposite quadrant + adjacent column + adjacent row
SEND_REQUIREMENTS = {
    # Cardinal: need opposite column/row
    SyncDirection.N: {'column': ['S']},
    SyncDirection.S: {'column': ['N']},
    SyncDirection.E: {'row': ['W']},
    SyncDirection.W: {'row': ['E']},
    # Diagonal: need opposite quadrant + adjacent column + adjacent row
    SyncDirection.NE: {'quadrant': ['SW'], 'column': ['S'], 'row': ['W']},
    SyncDirection.NW: {'quadrant': ['SE'], 'column': ['S'], 'row': ['E']},
    SyncDirection.SE: {'quadrant': ['NW'], 'column': ['N'], 'row': ['W']},
    SyncDirection.SW: {'quadrant': ['NE'], 'column': ['N'], 'row': ['E']},
}

# Special requirements for kamlet (0, 0) which is connected to the lamlet at N.
# When sending N (to lamlet), must include SE quadrant so lamlet sees whole grid.
# When sending S, E, or SE, must include N column (from lamlet).
SEND_REQUIREMENTS_ORIGIN = {
    SyncDirection.N: {'column': ['S'], 'quadrant': ['SE'], 'row': ['E']},
    SyncDirection.S: {'column': ['N']},
    SyncDirection.E: {'row': ['W'], 'column': ['N']},
    SyncDirection.W: {'row': ['E']},
    SyncDirection.NE: {'quadrant': ['SW'], 'column': ['S'], 'row': ['W']},
    SyncDirection.NW: {'quadrant': ['SE'], 'column': ['S'], 'row': ['E']},
    SyncDirection.SE: {'quadrant': ['NW'], 'column': ['N'], 'row': ['W']},
    SyncDirection.SW: {'quadrant': ['NE'], 'column': ['N'], 'row': ['E']},
}


@dataclass
class SyncState:
    """Tracks synchronization state for a single sync_ident."""
    sync_ident: int

    # Aggregation op for this sync. Set by the first start_sync / local_event
    # caller on any given kamlet; must match across all participants of the
    # same sync_ident. Receiving kamlets that start_sync from an incoming
    # packet leave this None until their own local_event supplies the op;
    # aggregation is deferred until then.
    op: Optional[SyncAggOp] = None
    # Width (in bits) of the aggregated value, used by signed MIN/MAX.
    # 32 for MIN_EL_INDEX / MAX_EL_INDEX by definition.
    width: int = 32

    # Whether this jamlet has locally seen the event
    local_seen: bool = False
    # None means no value provided, otherwise the local value for aggregation
    local_value: Optional[int] = None

    # Quadrant sync status (NE, NW, SE, SW)
    quadrant_synced: Dict[str, bool] = field(default_factory=lambda: {
        'NE': False, 'NW': False, 'SE': False, 'SW': False,
    })

    # Column sync status (N = north of us, S = south of us)
    column_synced: Dict[str, bool] = field(default_factory=lambda: {
        'N': False, 'S': False,
    })

    # Row sync status (E = east of us, W = west of us)
    row_synced: Dict[str, bool] = field(default_factory=lambda: {
        'E': False, 'W': False,
    })

    # Minimum values from each region (None means no value from that region)
    quadrant_values: Dict[str, Optional[int]] = field(default_factory=lambda: {
        'NE': None, 'NW': None, 'SE': None, 'SW': None,
    })
    column_values: Dict[str, Optional[int]] = field(default_factory=lambda: {
        'N': None, 'S': None,
    })
    row_values: Dict[str, Optional[int]] = field(default_factory=lambda: {
        'E': None, 'W': None,
    })

    # Track which directions we've already sent to
    sent_directions: Set[SyncDirection] = field(default_factory=set)

    # Whether this sync has completed
    completed: bool = False


@dataclass
class SyncPacket:
    """A synchronization packet to be sent to a neighbor.

    Bus sends data_width-bit words per cycle, where data_width = sync_bus_width - 1.
    Bus format per cycle: [data_width] = last_word flag, [data_width-1:0] = data word.

    Packet structure (in words):
    - Word 0: sync_ident (sync_ident_width bits, fits in data_width)
    - Words 1+: value bytes packed into data_width-bit words, if present

    Packet length determines whether value is present:
    - Length 1 word: sync only, no value
    - Length 2+ words: sync + value
    """
    sync_ident: int
    value: Optional[int]     # 1-4 bytes if present, None if no value

    def to_words(
        self,
        data_width: int,
        sync_ident_width: int,
        value_bytes: Optional[int] = None,
    ) -> list:
        """Serialize packet to a list of data_width-bit words.

        First word contains sync_ident. Remaining words contain value
        bytes packed little-endian. Total bit width is split into
        data_width-bit words using uint_to_list_of_uints.

        If value_bytes is given, the value is serialized as exactly that
        many bytes so all participants of a given sync_ident emit the
        same packet length (needed whenever the op's value width is >
        1 byte). Otherwise the value is auto-sized from bit_length.
        """
        if self.value is not None:
            if value_bytes is not None:
                n_value_bytes = value_bytes
                assert 1 <= n_value_bytes <= 4, (
                    f"value_bytes={n_value_bytes} out of range [1, 4]")
                assert self.value.bit_length() <= n_value_bytes * 8, (
                    f"Value {self.value} exceeds {n_value_bytes}-byte width")
            elif self.value == 0:
                n_value_bytes = 1
            else:
                n_value_bytes = (self.value.bit_length() + 7) // 8
            assert n_value_bytes <= 4, (
                f"Value {self.value} requires {n_value_bytes} bytes,"
                f" max is 4"
            )
            total_bits = sync_ident_width + n_value_bytes * 8
            combined = self.sync_ident | (self.value << sync_ident_width)
        else:
            total_bits = sync_ident_width
            combined = self.sync_ident
        n_words = (total_bits + data_width - 1) // data_width
        return uint_to_list_of_uints(combined, data_width, n_words)

    @classmethod
    def from_words(
        cls, words: list, data_width: int, sync_ident_width: int,
    ) -> 'SyncPacket':
        """Deserialize packet from data_width-bit words."""
        combined = list_of_uints_to_uint(words, data_width)
        ident_mask = (1 << sync_ident_width) - 1
        sync_ident = combined & ident_mask
        if len(words) > 1:
            value = combined >> sync_ident_width
        else:
            value = None
        return cls(sync_ident=sync_ident, value=value)


class Synchronizer:
    """
    Handles lamlet-wide synchronization for a single kamlet (or the lamlet).

    Each Synchronizer maintains state for multiple concurrent sync operations
    (identified by sync_ident) and communicates with all 8 neighbors via a
    dedicated synchronization network.

    The lamlet has a Synchronizer at position (0, -1). It connects to kamlet (0, 0)
    via S, and also to kamlet (1, 0) via SE when k_cols >= 2. It participates in
    the standard sync protocol like any other node.
    """

    def __init__(
        self,
        clock,
        params: ZamletParams,
        kx: int,
        ky: int,
        cache_table: 'CacheTable|None',
        monitor,
    ):
        self.clock = clock
        self.params = params
        self.kx = kx
        self.ky = ky
        self.cache_table = cache_table
        self.monitor = monitor

        # Validate coordinates
        if ky == -1:
            # Lamlet position
            assert kx == 0, f"Lamlet must be at kx=0, got kx={kx}"
        else:
            # Kamlet position
            assert 0 <= kx < params.k_cols, f"Kamlet kx={kx} out of range [0, {params.k_cols})"
            assert 0 <= ky < params.k_rows, f"Kamlet ky={ky} out of range [0, {params.k_rows})"

        # Calculate grid boundaries (kamlet grid, not jamlet grid)
        self.total_cols = params.k_cols
        self.total_rows = params.k_rows

        # Input/output buffers for each of 8 directions
        self._input_buffers: Dict[SyncDirection, Queue] = {
            d: Queue(8) for d in SyncDirection
        }
        self._output_buffers: Dict[SyncDirection, Queue] = {
            d: Queue(8) for d in SyncDirection
        }

        # Active sync operations indexed by sync_ident
        self._sync_states: Dict[int, SyncState] = {}

        # Fault sync chaining: trigger_ident -> target_ident.
        # When trigger completes, fire local_event for target with
        # value=0 if trigger's min is not None, else value=None.
        self._fault_chains: Dict[int, int] = {}

        # Packets being assembled from input (may span multiple cycles)
        self._partial_packets: Dict[SyncDirection, List[int]] = {
            d: [] for d in SyncDirection
        }

        # Packets being sent (word-by-word, one word per cycle per direction)
        self._outgoing_packets: Dict[SyncDirection, List[int]] = {}


    def has_neighbor(self, direction: SyncDirection) -> bool:
        """Check if there's a neighbor in the given direction."""
        dx, dy = self._direction_delta(direction)
        nx, ny = self.kx + dx, self.ky + dy
        if self.ky == -1:
            # Lamlet at (0, -1) connects to any kamlet in its neighbor ring
            # e.g. S to kamlet (0,0), SE to kamlet (1,0) if k_cols >= 2
            return 0 <= nx < self.total_cols and 0 <= ny < self.total_rows
        # Kamlet (0, 0) has the lamlet as its N neighbor
        if nx == 0 and ny == -1:
            return True
        return 0 <= nx < self.total_cols and 0 <= ny < self.total_rows

    def _direction_delta(self, direction: SyncDirection) -> tuple:
        """Get (dx, dy) for a direction."""
        deltas = {
            SyncDirection.N: (0, -1),
            SyncDirection.S: (0, 1),
            SyncDirection.E: (1, 0),
            SyncDirection.W: (-1, 0),
            SyncDirection.NE: (1, -1),
            SyncDirection.NW: (-1, -1),
            SyncDirection.SE: (1, 1),
            SyncDirection.SW: (-1, 1),
        }
        return deltas[direction]

    # Region ⇔ direction mappings. A region is "present" iff the
    # corresponding neighbor in that direction exists; this keeps auto-sync
    # consistent with packet delivery. In particular, the lamlet at (0,-1)
    # is a direct NW neighbor of kamlet (1,0) and a direct N neighbor of
    # kamlet (0,0); both have_neighbor and the region helpers must agree.
    _QUADRANT_DIRECTION = {
        'NE': SyncDirection.NE, 'NW': SyncDirection.NW,
        'SE': SyncDirection.SE, 'SW': SyncDirection.SW,
    }
    _COLUMN_DIRECTION = {'N': SyncDirection.N, 'S': SyncDirection.S}
    _ROW_DIRECTION = {'E': SyncDirection.E, 'W': SyncDirection.W}

    def _has_quadrant(self, quadrant: str) -> bool:
        return self.has_neighbor(self._QUADRANT_DIRECTION[quadrant])

    def _has_column_region(self, region: str) -> bool:
        return self.has_neighbor(self._COLUMN_DIRECTION[region])

    def _has_row_region(self, region: str) -> bool:
        return self.has_neighbor(self._ROW_DIRECTION[region])

    def start_sync(
        self,
        sync_ident: int,
        op: Optional[SyncAggOp] = None,
        width: int = 32,
    ):
        """Start tracking a new synchronization operation.

        `op` may be left None when the sync is auto-created on receiving a
        packet before this kamlet's own local_event has fired. In that case,
        raw per-region values are stored and aggregation is deferred until
        local_event supplies the op.
        """
        assert sync_ident not in self._sync_states, \
            f"sync_ident={sync_ident} already exists at ({self.kx},{self.ky})"

        state = SyncState(sync_ident=sync_ident, op=op, width=width)

        # Mark non-existent regions as already synced
        for q in ['NE', 'NW', 'SE', 'SW']:
            if not self._has_quadrant(q):
                state.quadrant_synced[q] = True

        for c in ['N', 'S']:
            if not self._has_column_region(c):
                state.column_synced[c] = True

        for r in ['E', 'W']:
            if not self._has_row_region(r):
                state.row_synced[r] = True

        self._sync_states[sync_ident] = state
        auto_q = [q for q in ['NE', 'NW', 'SE', 'SW'] if state.quadrant_synced[q]]
        auto_c = [c for c in ['N', 'S'] if state.column_synced[c]]
        auto_r = [r for r in ['E', 'W'] if state.row_synced[r]]
        logger.debug(f'{self.clock.cycle}: SYNC_START: synchronizer ({self.kx},{self.ky}) '
                     f'sync_ident={sync_ident} auto_synced: quad={auto_q} col={auto_c} row={auto_r}')

    def local_event(
        self,
        sync_ident: int,
        value: Optional[int] = None,
        op: SyncAggOp = SyncAggOp.MIN,
        width: int = 32,
    ):
        """Report that this kamlet has seen the event.

        `op` declares the aggregation mode for this sync_ident. If the sync
        was auto-started from an earlier incoming packet (op still None),
        this call supplies it. If the sync already has an op set by a
        prior caller, the passed op must match.
        """
        # sync_ident may be reused after a previous sync completed - clear old state
        if sync_ident in self._sync_states and self._sync_states[sync_ident].completed:
            del self._sync_states[sync_ident]
        if sync_ident not in self._sync_states:
            self.start_sync(sync_ident, op=op, width=width)

        state = self._sync_states[sync_ident]
        if state.op is None:
            state.op = op
            state.width = width
        else:
            assert state.op == op, (
                f"sync_ident={sync_ident} already has op={state.op}, "
                f"caller supplied {op}")
            assert state.width == width, (
                f"sync_ident={sync_ident} already has width={state.width}, "
                f"caller supplied {width}")
        state.local_seen = True
        state.local_value = value
        logger.debug(f'{self.clock.cycle}: SYNC_LOCAL: synchronizer ({self.kx},{self.ky}) '
                     f'sync_ident={sync_ident} value={value} op={op.name}')
        self.monitor.record_sync_local_event(sync_ident, self.kx, self.ky, value)
        self._update_completed(sync_ident)

    def _all_sends_complete(self, state: SyncState) -> bool:
        """Check if we've sent to all neighbors that exist."""
        for direction in SyncDirection:
            if self.has_neighbor(direction) and direction not in state.sent_directions:
                return False
        return True

    def has_sync(self, sync_ident: int) -> bool:
        """Check if a sync operation exists for this sync_ident."""
        return sync_ident in self._sync_states

    def has_local_seen(self, sync_ident: int) -> bool:
        """Check if a sync operation exists for this sync_ident."""
        return sync_ident in self._sync_states and self._sync_states[sync_ident].local_seen

    def is_complete(self, sync_ident: int) -> bool:
        """Check if synchronization is complete (all kamlets have seen the event)."""
        state = self._sync_states.get(sync_ident)
        if state is None:
            return False
        return state.completed

    def _is_complete(self, state: SyncState) -> bool:
        """Internal check for completion conditions."""
        if not state.local_seen:
            return False

        # Must have received from all regions
        missing_q = [q for q, v in state.quadrant_synced.items() if not v]
        missing_c = [c for c, v in state.column_synced.items() if not v]
        missing_r = [r for r, v in state.row_synced.items() if not v]
        if missing_q or missing_c or missing_r:
            logger.debug(f'{self.clock.cycle}: SYNC_INCOMPLETE: synchronizer ({self.kx},{self.ky}) '
                         f'sync_ident={state.sync_ident} missing: quad={missing_q} col={missing_c} row={missing_r}')
            return False

        # Must have sent to all neighbors
        sends_complete = self._all_sends_complete(state)
        if not sends_complete:
            missing_sends = [d.name for d in SyncDirection
                            if self.has_neighbor(d) and d not in state.sent_directions]
            logger.debug(f'{self.clock.cycle}: SYNC_INCOMPLETE: synchronizer ({self.kx},{self.ky}) '
                         f'sync_ident={state.sync_ident} missing_sends={missing_sends}')
        return sends_complete

    def get_aggregated_value(self, sync_ident: int) -> Optional[int]:
        """Get the op-aggregated value across all kamlets.

        Returns None if no values were provided by any kamlet.
        """
        if sync_ident not in self._sync_states:
            return None

        state = self._sync_states[sync_ident]

        values = [state.local_value]
        for v in state.quadrant_values.values():
            values.append(v)
        for v in state.column_values.values():
            values.append(v)
        for v in state.row_values.values():
            values.append(v)

        assert state.op is not None, (
            f"sync_ident={sync_ident} has no op set; get_aggregated_value "
            f"called before local_event")
        return aggregate_sync_values(state.op, values, width=state.width)

    def clear_sync(self, sync_ident: int):
        """Clear a completed synchronization."""
        del self._sync_states[sync_ident]

    def chain_fault_sync(self, trigger_ident: int, target_ident: int):
        """Chain fault syncs: when trigger completes, fire local_event for target.

        If trigger's min_value is not None (fault detected), injects value=0
        to suppress all non-idempotent accesses in the target chunk.
        Otherwise injects value=None.

        If the trigger has already completed, fires immediately.
        """
        state = self._sync_states.get(trigger_ident)
        if state is not None and state.completed:
            min_value = self.get_aggregated_value(trigger_ident)
            self.local_event(target_ident, value=min_value)
        else:
            self._fault_chains[trigger_ident] = target_ident

    def _update_completed(self, sync_ident: int):
        """Check if sync is now complete and log once if so."""
        state = self._sync_states.get(sync_ident)
        if state is None or state.completed:
            return
        if self._is_complete(state):
            state.completed = True
            min_value = self.get_aggregated_value(sync_ident)
            logger.debug(f'{self.clock.cycle}: SYNC_COMPLETE: synchronizer ({self.kx},{self.ky}) '
                         f'sync_ident={sync_ident} min_value={min_value}')
            self.monitor.record_sync_local_complete(sync_ident, self.kx, self.ky, min_value)
            # Fire chained fault sync if any
            if sync_ident in self._fault_chains:
                target = self._fault_chains.pop(sync_ident)
                self.local_event(target, value=min_value)

    def _get_send_requirements(self, direction: SyncDirection) -> dict:
        """Get send requirements for a direction. Kamlet (0,0) has special requirements."""
        if self.kx == 0 and self.ky == 0:
            return SEND_REQUIREMENTS_ORIGIN[direction]
        return SEND_REQUIREMENTS[direction]

    def _should_send(self, state: SyncState, direction: SyncDirection) -> bool:
        """Determine if we should send a sync message in the given direction."""
        if not self.has_neighbor(direction):
            return False

        if direction in state.sent_directions:
            return False

        if not state.local_seen:
            return False

        # Check all requirements for this direction
        reqs = self._get_send_requirements(direction)

        missing = []
        for q in reqs.get('quadrant', []):
            if not state.quadrant_synced[q]:
                missing.append(f'quad_{q}')

        for c in reqs.get('column', []):
            if not state.column_synced[c]:
                missing.append(f'col_{c}')

        for r in reqs.get('row', []):
            if not state.row_synced[r]:
                missing.append(f'row_{r}')

        if missing:
            logger.debug(f'{self.clock.cycle}: SYNC_SEND_BLOCKED: ({self.kx},{self.ky}) '
                         f'sync_ident={state.sync_ident} dir={direction.name} missing={missing}')
            return False

        return True

    def _get_value_for_direction(
        self, state: SyncState, direction: SyncDirection,
    ) -> Optional[int]:
        """Calculate op-aggregated value to send in a direction.

        Combines local_value with the values from all regions this send
        depends on. Returns None if no values are available.
        """
        values = [state.local_value]
        reqs = self._get_send_requirements(direction)
        for q in reqs.get('quadrant', []):
            values.append(state.quadrant_values[q])
        for c in reqs.get('column', []):
            values.append(state.column_values[c])
        for r in reqs.get('row', []):
            values.append(state.row_values[r])
        assert state.op is not None, (
            f"sync_ident={state.sync_ident} has no op set; cannot send "
            f"(should_send should have gated on local_seen)")
        return aggregate_sync_values(state.op, values, width=state.width)

    def _process_received_packet(self, packet: SyncPacket, from_direction: SyncDirection):
        """Process a received sync packet from a neighbor."""
        sync_ident = packet.sync_ident

        # sync_ident may be reused after a previous sync completed - clear old state
        if sync_ident in self._sync_states and self._sync_states[sync_ident].completed:
            del self._sync_states[sync_ident]
        if sync_ident not in self._sync_states:
            self.start_sync(sync_ident)

        state = self._sync_states[sync_ident]

        # Determine which region this packet tells us about based on where it came from
        # If we receive from NE, it tells us NE quadrant is synced
        # If we receive from N, it tells us N column is synced
        # etc.
        #
        # Each (sync_ident, region) slot is written exactly once per
        # generation: the sender's _should_send dedupes on sent_directions,
        # and the lamlet's IdentQuery-gated allocation ensures sync_ident X
        # is not reissued to any kamlet until every kamlet has drained X's
        # prior generation. The assert documents and enforces this.
        # Aggregation across the local value and region values is deferred
        # to _get_value_for_direction / get_aggregated_value, which depend
        # on the op being known.
        if from_direction in [SyncDirection.NE, SyncDirection.NW,
                               SyncDirection.SE, SyncDirection.SW]:
            region = from_direction.name
            assert not state.quadrant_synced[region], (
                f"double packet from quadrant {region} for "
                f"sync_ident={sync_ident} at ({self.kx},{self.ky})")
            state.quadrant_synced[region] = True
            state.quadrant_values[region] = packet.value
        elif from_direction in [SyncDirection.N, SyncDirection.S]:
            region = from_direction.name
            assert not state.column_synced[region], (
                f"double packet from column {region} for "
                f"sync_ident={sync_ident} at ({self.kx},{self.ky})")
            state.column_synced[region] = True
            state.column_values[region] = packet.value
        elif from_direction in [SyncDirection.E, SyncDirection.W]:
            region = from_direction.name
            assert not state.row_synced[region], (
                f"double packet from row {region} for "
                f"sync_ident={sync_ident} at ({self.kx},{self.ky})")
            state.row_synced[region] = True
            state.row_values[region] = packet.value

        logger.debug(f'{self.clock.cycle}: SYNC_RECV: synchronizer ({self.kx},{self.ky}) '
                     f'from={from_direction.name} sync_ident={sync_ident} '
                     f'value={packet.value}')
        self._update_completed(sync_ident)

    def update(self):
        """Update buffers (call at end of cycle)."""
        for buf in self._input_buffers.values():
            buf.update()
        for buf in self._output_buffers.values():
            buf.update()

    async def run(self):
        """Main loop for the synchronizer."""
        data_width = self.params.sync_bus_width - 1
        sync_ident_width = self.params.sync_ident_width
        data_mask = (1 << data_width) - 1

        while True:
            await self.clock.next_cycle

            # Process incoming packets (one word per direction per cycle)
            for direction in SyncDirection:
                in_buf = self._input_buffers[direction]
                partial = self._partial_packets[direction]

                if in_buf:
                    # [data_width] = last_word, [data_width-1:0] = data
                    bus_val = in_buf.popleft()
                    last_word = (bus_val >> data_width) & 1
                    data_word = bus_val & data_mask
                    partial.append(data_word)

                    # Check if we have a complete packet
                    if last_word:
                        packet = SyncPacket.from_words(
                            partial, data_width, sync_ident_width,
                        )
                        self._process_received_packet(packet, direction)
                        partial.clear()

            # Continue sending any packets in progress (one word per direction per cycle)
            for direction in SyncDirection:
                if direction in self._outgoing_packets and self._outgoing_packets[direction]:
                    out_buf = self._output_buffers[direction]
                    if out_buf.can_append():
                        # [data_width] = last_word, [data_width-1:0] = data
                        data_word = self._outgoing_packets[direction].pop(0)
                        last_word = 1 if not self._outgoing_packets[direction] else 0
                        bus_val = (last_word << data_width) | data_word
                        out_buf.append(bus_val)
                        if not self._outgoing_packets[direction]:
                            del self._outgoing_packets[direction]

            # Start new packets if we should send and no packet in progress for that direction
            for state in list(self._sync_states.values()):
                for direction in SyncDirection:
                    if direction not in self._outgoing_packets and self._should_send(state, direction):
                        value = self._get_value_for_direction(state, direction)
                        packet = SyncPacket(
                            sync_ident=state.sync_ident,
                            value=value,
                        )
                        # Fixed value width so all participants of a sync_ident
                        # emit same-length packets (required once we support
                        # widths > 8 bits like MIN_EL_INDEX's 32-bit values).
                        value_bytes = (state.width + 7) // 8
                        packet_words = packet.to_words(
                            data_width, sync_ident_width,
                            value_bytes=value_bytes,
                        )
                        self._outgoing_packets[direction] = packet_words
                        state.sent_directions.add(direction)
                        logger.debug(f'{self.clock.cycle}: SYNC_SEND: synchronizer ({self.kx},{self.ky}) '
                                     f'dir={direction.name} sync_ident={state.sync_ident} '
                                     f'value={value}')

            # Check for completion after sends are processed
            for state in list(self._sync_states.values()):
                self._update_completed(state.sync_ident)

    def can_receive(self, direction: SyncDirection) -> bool:
        """Check if we can receive a byte from the given direction."""
        return self._input_buffers[direction].can_append()

    def receive(self, direction: SyncDirection, byte_val: int):
        """Receive a byte from a neighbor (called by external network)."""
        assert self._input_buffers[direction].can_append()
        self._input_buffers[direction].append(byte_val)
        logger.debug(
            f'{self.clock.cycle}: SYNC_RX_EXTERNAL at ({self.kx},{self.ky}) '
            f'from_dir={direction.name} byte_val=0x{byte_val:x} '
            f'in_buf_size={len(self._input_buffers[direction])}')

    def has_output(self, direction: SyncDirection) -> bool:
        """Check if there's output to send in a direction."""
        return bool(self._output_buffers[direction])

    def get_output(self, direction: SyncDirection) -> Optional[int]:
        """Get the next output byte for a direction."""
        if self._output_buffers[direction]:
            return self._output_buffers[direction].popleft()
        return None

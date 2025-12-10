"""
Lamlet-wide Synchronization Network

This module implements a dedicated synchronization network for tracking when events
have occurred across all kamlets in a lamlet. It supports optional minimum value
aggregation.

Network Architecture:
- Separate 9-bit wide bus network (not using the main router network)
- Direct connections to all 8 neighbors (N, S, E, W, NE, NW, SE, SW)
- No routing - packets only go to immediate neighbors

Bus Format (9 bits per cycle):
- [8] = last_byte (1 if this is the final byte of packet)
- [7:0] = data byte

Packet Format:
- Byte 0: sync_ident (8 bits)
- Bytes 1+: value (1-4 bytes, little-endian) if present

Packet length determines whether value is present:
- Length 1: sync only, no value
- Length 2-5: sync + 1-4 byte value

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

from zamlet.params import LamletParams
from zamlet.utils import Queue

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

    # Whether this jamlet has locally seen the event
    local_seen: bool = False
    # None means no value provided, otherwise the local value for min aggregation
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

    9-bit bus per cycle: [8] = last_byte, [7:0] = data

    Packet structure:
    - Byte 0: sync_ident (8 bits)
    - Bytes 1+: value (1-4 bytes, little-endian) if present

    Packet length determines whether value is present:
    - Length 1: sync only, no value
    - Length 2-5: sync + 1-4 byte value
    """
    sync_ident: int          # 8 bits
    value: Optional[int]     # 1-4 bytes if present, None if no value

    def to_bytes(self) -> bytes:
        """Serialize packet to bytes for transmission."""
        result = bytes([self.sync_ident & 0xFF])
        if self.value is not None:
            # Determine minimum bytes needed for value
            if self.value == 0:
                n_bytes = 1
            else:
                n_bytes = (self.value.bit_length() + 7) // 8
            assert n_bytes <= 4, f"Value {self.value} requires {n_bytes} bytes, max is 4"
            result += self.value.to_bytes(n_bytes, 'little')
        return result

    @classmethod
    def from_bytes(cls, data: bytes) -> 'SyncPacket':
        """Deserialize packet from bytes."""
        sync_ident = data[0]
        value = None
        if len(data) > 1:
            value = int.from_bytes(data[1:], 'little')
        return cls(sync_ident=sync_ident, value=value)

    def length(self) -> int:
        """Return packet length in bytes."""
        if self.value is None:
            return 1
        if self.value == 0:
            return 2
        n_bytes = (self.value.bit_length() + 7) // 8
        return 1 + n_bytes


class Synchronizer:
    """
    Handles lamlet-wide synchronization for a single kamlet (or the lamlet).

    Each Synchronizer maintains state for multiple concurrent sync operations
    (identified by sync_ident) and communicates with all 8 neighbors via a
    dedicated 8-bit synchronization network.

    The lamlet can also have a Synchronizer at position (0, -1). It only connects
    to kamlet (0, 0) via the S direction. When y == -1, the synchronizer
    uses simplified logic: it just waits to receive from S (and optionally SE if
    k_cols > 1), then marks the sync complete.
    """

    def __init__(
        self,
        clock,
        params: LamletParams,
        x: int,
        y: int,
        cache_table: 'CacheTable|None',
        monitor,
    ):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y
        self.cache_table = cache_table
        self.monitor = monitor

        # Validate coordinates
        if y == -1:
            # Lamlet position
            assert x == 0, f"Lamlet must be at x=0, got x={x}"
        else:
            # Kamlet position
            assert 0 <= x < params.k_cols, f"Kamlet x={x} out of range [0, {params.k_cols})"
            assert 0 <= y < params.k_rows, f"Kamlet y={y} out of range [0, {params.k_rows})"

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

        # Packets being assembled from input (may span multiple cycles)
        self._partial_packets: Dict[SyncDirection, bytearray] = {
            d: bytearray() for d in SyncDirection
        }

        # Packets being sent (byte-by-byte, one byte per cycle per direction)
        self._outgoing_packets: Dict[SyncDirection, List[int]] = {}


    def has_neighbor(self, direction: SyncDirection) -> bool:
        """Check if there's a neighbor in the given direction."""
        if self.y == -1:
            # Lamlet at (0, -1) only connects S to kamlet (0,0)
            return direction == SyncDirection.S
        dx, dy = self._direction_delta(direction)
        nx, ny = self.x + dx, self.y + dy
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

    def _has_quadrant(self, quadrant: str) -> bool:
        """Check if any kamlets exist in the given quadrant."""
        if self.y == -1:
            return False
        if quadrant == 'NE':
            return self.x < self.total_cols - 1 and self.y > 0
        elif quadrant == 'NW':
            return self.x > 0 and self.y > 0
        elif quadrant == 'SE':
            return self.x < self.total_cols - 1 and self.y < self.total_rows - 1
        elif quadrant == 'SW':
            return self.x > 0 and self.y < self.total_rows - 1
        return False

    def _has_column_region(self, region: str) -> bool:
        """Check if there are kamlets in column north/south of us."""
        if self.y == -1:
            # Lamlet: only S column exists (kamlets 0,0 through 0,k_rows-1)
            return region == 'S'
        if region == 'N':
            # For kamlet (0,0), the lamlet is to the north
            if self.x == 0 and self.y == 0:
                return True
            return self.y > 0
        elif region == 'S':
            return self.y < self.total_rows - 1
        return False

    def _has_row_region(self, region: str) -> bool:
        """Check if there are kamlets in row east/west of us."""
        if self.y == -1:
            # Lamlet: no row neighbors (lamlet is not in the kamlet grid row)
            return False
        if region == 'E':
            return self.x < self.total_cols - 1
        elif region == 'W':
            return self.x > 0
        return False

    def start_sync(self, sync_ident: int):
        """Start tracking a new synchronization operation."""
        if sync_ident in self._sync_states:
            return

        state = SyncState(sync_ident=sync_ident)

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
        logger.debug(f'{self.clock.cycle}: SYNC_START: synchronizer ({self.x},{self.y}) '
                     f'sync_ident={sync_ident}')

    def local_event(self, sync_ident: int, value: Optional[int] = None):
        """Report that this kamlet has seen the event."""
        if sync_ident not in self._sync_states:
            self.start_sync(sync_ident)

        state = self._sync_states[sync_ident]
        state.local_seen = True
        state.local_value = value
        logger.debug(f'{self.clock.cycle}: SYNC_LOCAL: synchronizer ({self.x},{self.y}) '
                     f'sync_ident={sync_ident} value={value}')
        self.monitor.record_sync_local_event(sync_ident, self.x, self.y, value)
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
        if not (all(state.quadrant_synced.values()) and
                all(state.column_synced.values()) and
                all(state.row_synced.values())):
            return False

        # Must have sent to all neighbors
        return self._all_sends_complete(state)

    def get_min_value(self, sync_ident: int) -> Optional[int]:
        """Get the minimum value across all kamlets.

        Returns None if no values were provided by any kamlet.
        """
        if sync_ident not in self._sync_states:
            return None

        state = self._sync_states[sync_ident]

        values = []
        if state.local_value is not None:
            values.append(state.local_value)
        for v in state.quadrant_values.values():
            if v is not None:
                values.append(v)
        for v in state.column_values.values():
            if v is not None:
                values.append(v)
        for v in state.row_values.values():
            if v is not None:
                values.append(v)

        return min(values) if values else None

    def clear_sync(self, sync_ident: int):
        """Clear a completed synchronization."""
        del self._sync_states[sync_ident]

    def _update_completed(self, sync_ident: int):
        """Check if sync is now complete and log once if so."""
        state = self._sync_states.get(sync_ident)
        if state is None or state.completed:
            return
        if self._is_complete(state):
            state.completed = True
            min_value = self.get_min_value(sync_ident)
            logger.debug(f'{self.clock.cycle}: SYNC_COMPLETE: synchronizer ({self.x},{self.y}) '
                         f'sync_ident={sync_ident} min_value={min_value}')
            self.monitor.record_sync_local_complete(sync_ident, self.x, self.y, min_value)

    def _get_send_requirements(self, direction: SyncDirection) -> dict:
        """Get send requirements for a direction. Kamlet (0,0) has special requirements."""
        if self.x == 0 and self.y == 0:
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

        for q in reqs.get('quadrant', []):
            if not state.quadrant_synced[q]:
                return False

        for c in reqs.get('column', []):
            if not state.column_synced[c]:
                return False

        for r in reqs.get('row', []):
            if not state.row_synced[r]:
                return False

        return True

    def _get_min_for_direction(self, state: SyncState, direction: SyncDirection) -> Optional[int]:
        """Calculate min value to send in a direction (includes local + all required regions).

        Returns None if no values are available.
        """
        values = []
        if state.local_value is not None:
            values.append(state.local_value)

        reqs = self._get_send_requirements(direction)

        for q in reqs.get('quadrant', []):
            if state.quadrant_values[q] is not None:
                values.append(state.quadrant_values[q])

        for c in reqs.get('column', []):
            if state.column_values[c] is not None:
                values.append(state.column_values[c])

        for r in reqs.get('row', []):
            if state.row_values[r] is not None:
                values.append(state.row_values[r])

        return min(values) if values else None

    def _process_received_packet(self, packet: SyncPacket, from_direction: SyncDirection):
        """Process a received sync packet from a neighbor."""
        sync_ident = packet.sync_ident

        if sync_ident not in self._sync_states:
            self.start_sync(sync_ident)

        state = self._sync_states[sync_ident]

        # Determine which region this packet tells us about based on where it came from
        # If we receive from NE, it tells us NE quadrant is synced
        # If we receive from N, it tells us N column is synced
        # etc.

        if from_direction in [SyncDirection.NE, SyncDirection.NW,
                               SyncDirection.SE, SyncDirection.SW]:
            region = from_direction.name
            state.quadrant_synced[region] = True
            if packet.value is not None:
                if state.quadrant_values[region] is None:
                    state.quadrant_values[region] = packet.value
                else:
                    state.quadrant_values[region] = min(state.quadrant_values[region],
                                                        packet.value)
        elif from_direction in [SyncDirection.N, SyncDirection.S]:
            region = from_direction.name
            state.column_synced[region] = True
            if packet.value is not None:
                if state.column_values[region] is None:
                    state.column_values[region] = packet.value
                else:
                    state.column_values[region] = min(state.column_values[region],
                                                      packet.value)
        elif from_direction in [SyncDirection.E, SyncDirection.W]:
            region = from_direction.name
            state.row_synced[region] = True
            if packet.value is not None:
                if state.row_values[region] is None:
                    state.row_values[region] = packet.value
                else:
                    state.row_values[region] = min(state.row_values[region],
                                                   packet.value)

        logger.debug(f'{self.clock.cycle}: SYNC_RECV: synchronizer ({self.x},{self.y}) '
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
        while True:
            await self.clock.next_cycle

            # Process incoming packets (one byte per direction per cycle)
            for direction in SyncDirection:
                in_buf = self._input_buffers[direction]
                partial = self._partial_packets[direction]

                if in_buf:
                    # 9-bit bus: [8] = last_byte, [7:0] = data
                    bus_val = in_buf.popleft()
                    last_byte = (bus_val >> 8) & 1
                    data_byte = bus_val & 0xFF
                    partial.append(data_byte)

                    # Check if we have a complete packet
                    if last_byte:
                        packet = SyncPacket.from_bytes(bytes(partial))
                        self._process_received_packet(packet, direction)
                        partial.clear()

            # Continue sending any packets in progress (one byte per direction per cycle)
            for direction in SyncDirection:
                if direction in self._outgoing_packets and self._outgoing_packets[direction]:
                    out_buf = self._output_buffers[direction]
                    if out_buf.can_append():
                        # 9-bit bus: [8] = last_byte, [7:0] = data
                        data_byte = self._outgoing_packets[direction].pop(0)
                        last_byte = 1 if not self._outgoing_packets[direction] else 0
                        bus_val = (last_byte << 8) | data_byte
                        out_buf.append(bus_val)
                        if not self._outgoing_packets[direction]:
                            del self._outgoing_packets[direction]

            # Start new packets if we should send and no packet in progress for that direction
            for state in list(self._sync_states.values()):
                for direction in SyncDirection:
                    if direction not in self._outgoing_packets and self._should_send(state, direction):
                        value = self._get_min_for_direction(state, direction)
                        packet = SyncPacket(
                            sync_ident=state.sync_ident,
                            value=value,
                        )
                        packet_bytes = list(packet.to_bytes())
                        self._outgoing_packets[direction] = packet_bytes
                        state.sent_directions.add(direction)
                        logger.debug(f'{self.clock.cycle}: SYNC_SEND: synchronizer ({self.x},{self.y}) '
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

    def has_output(self, direction: SyncDirection) -> bool:
        """Check if there's output to send in a direction."""
        return bool(self._output_buffers[direction])

    def get_output(self, direction: SyncDirection) -> Optional[int]:
        """Get the next output byte for a direction."""
        if self._output_buffers[direction]:
            return self._output_buffers[direction].popleft()
        return None

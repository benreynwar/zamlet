"""
Lamlet-wide Synchronization Network

This module implements a dedicated synchronization network for tracking when events
have occurred across all kamlets in a lamlet. It supports optional minimum value
aggregation.

Network Architecture:
- Separate 8-bit wide bus network (not using the main router network)
- Direct connections to all 8 neighbors (N, S, E, W, NE, NW, SE, SW)
- No routing - packets only go to immediate neighbors

Packet Format (8 bits per cycle):
- Byte 0: [7:6] reserved (2), [5:1] sync_ident (5), [0] has_value (1)
- Bytes 1-4: value (32-bit, little-endian) - only if has_value=1

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


@dataclass
class SyncState:
    """Tracks synchronization state for a single sync_ident."""
    sync_ident: int
    has_value: bool = False

    # Whether this jamlet has locally seen the event
    local_seen: bool = False
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

    # Minimum values from each region (if has_value)
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


@dataclass
class SyncPacket:
    """A synchronization packet to be sent to a neighbor."""
    sync_ident: int          # 7 bits
    has_value: bool          # 1 bit
    value: Optional[int]     # 32 bits if has_value

    def to_bytes(self) -> bytes:
        """Serialize packet to bytes for transmission."""
        # Byte 0: [7] has_value, [6:0] sync_ident (7 bits)
        # Bytes 1-4: value (32-bit, if has_value=1)
        byte0 = (0x80 if self.has_value else 0) | (self.sync_ident & 0x7F)
        result = bytes([byte0])
        if self.has_value and self.value is not None:
            result += self.value.to_bytes(4, 'little')
        return result

    @classmethod
    def from_bytes(cls, data: bytes) -> 'SyncPacket':
        """Deserialize packet from bytes."""
        byte0 = data[0]
        has_value = (byte0 & 0x80) != 0
        sync_ident = byte0 & 0x7F
        value = None
        if has_value and len(data) >= 5:
            value = int.from_bytes(data[1:5], 'little')
        return cls(sync_ident=sync_ident, has_value=has_value, value=value)

    def length(self) -> int:
        """Return packet length in bytes."""
        return 5 if self.has_value else 1


class Synchronizer:
    """
    Handles lamlet-wide synchronization for a single kamlet.

    Each Synchronizer maintains state for multiple concurrent sync operations
    (identified by sync_ident) and communicates with all 8 neighbors via a
    dedicated 8-bit synchronization network.
    """

    def __init__(self, clock, params: LamletParams, x: int, y: int, cache_table: 'CacheTable|None'):
        self.clock = clock
        self.params = params
        self.x = x
        self.y = y
        self.cache_table = cache_table

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
        dx, dy = self._direction_delta(direction)
        nx, ny = self.x + dx, self.y + dy
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
        if region == 'N':
            return self.y > 0
        elif region == 'S':
            return self.y < self.total_rows - 1
        return False

    def _has_row_region(self, region: str) -> bool:
        """Check if there are kamlets in row east/west of us."""
        if region == 'E':
            return self.x < self.total_cols - 1
        elif region == 'W':
            return self.x > 0
        return False

    def start_sync(self, sync_ident: int, has_value: bool = False):
        """Start tracking a new synchronization operation."""
        if sync_ident in self._sync_states:
            return

        state = SyncState(sync_ident=sync_ident, has_value=has_value)

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
                     f'sync_ident={sync_ident} has_value={has_value}')

    def local_event(self, sync_ident: int, value: Optional[int] = None):
        """Report that this kamlet has seen the event."""
        if sync_ident not in self._sync_states:
            self.start_sync(sync_ident, has_value=(value is not None))

        state = self._sync_states[sync_ident]
        state.local_seen = True
        state.local_value = value
        logger.debug(f'{self.clock.cycle}: SYNC_LOCAL: synchronizer ({self.x},{self.y}) '
                     f'sync_ident={sync_ident} value={value}')
        self._notify_if_complete(sync_ident)

    def _all_sends_complete(self, state: SyncState) -> bool:
        """Check if we've sent to all neighbors that exist."""
        for direction in SyncDirection:
            if self.has_neighbor(direction) and direction not in state.sent_directions:
                return False
        return True

    def is_complete(self, sync_ident: int) -> bool:
        """Check if synchronization is complete (all kamlets have seen the event)."""
        if sync_ident not in self._sync_states:
            return False

        state = self._sync_states[sync_ident]
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
        """Get the minimum value across all kamlets."""
        if sync_ident not in self._sync_states:
            return None

        state = self._sync_states[sync_ident]
        if not state.has_value:
            return None

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
        if sync_ident in self._sync_states:
            del self._sync_states[sync_ident]

    def _notify_if_complete(self, sync_ident: int):
        """If sync is complete, set the waiting item's sync_state to COMPLETE."""
        if self.is_complete(sync_ident):
            if self.cache_table is not None:
                witem = self.cache_table.get_waiting_item_by_instr_ident(sync_ident)
                assert witem is not None
                assert witem.sync_state == WaitingItemSyncState.IN_PROGRESS
                witem.sync_state = WaitingItemSyncState.COMPLETE
                del self._sync_states[sync_ident]
            logger.debug(f'{self.clock.cycle}: SYNC_COMPLETE: synchronizer ({self.x},{self.y}) '
                         f'sync_ident={sync_ident}')

    def _should_send(self, state: SyncState, direction: SyncDirection) -> bool:
        """Determine if we should send a sync message in the given direction."""
        if not self.has_neighbor(direction):
            return False

        if direction in state.sent_directions:
            return False

        if not state.local_seen:
            return False

        # Check all requirements for this direction
        reqs = SEND_REQUIREMENTS[direction]

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
        """Calculate min value to send in a direction (includes local + all required regions)."""
        if not state.has_value:
            return None

        values = []
        if state.local_value is not None:
            values.append(state.local_value)

        reqs = SEND_REQUIREMENTS[direction]

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
            self.start_sync(sync_ident, has_value=packet.has_value)

        state = self._sync_states[sync_ident]

        # Determine which region this packet tells us about based on where it came from
        # If we receive from NE, it tells us NE quadrant is synced
        # If we receive from N, it tells us N column is synced
        # etc.

        if from_direction in [SyncDirection.NE, SyncDirection.NW,
                               SyncDirection.SE, SyncDirection.SW]:
            region = from_direction.name
            state.quadrant_synced[region] = True
            if packet.has_value and packet.value is not None:
                if state.quadrant_values[region] is None:
                    state.quadrant_values[region] = packet.value
                else:
                    state.quadrant_values[region] = min(state.quadrant_values[region],
                                                        packet.value)
        elif from_direction in [SyncDirection.N, SyncDirection.S]:
            region = from_direction.name
            state.column_synced[region] = True
            if packet.has_value and packet.value is not None:
                if state.column_values[region] is None:
                    state.column_values[region] = packet.value
                else:
                    state.column_values[region] = min(state.column_values[region],
                                                      packet.value)
        elif from_direction in [SyncDirection.E, SyncDirection.W]:
            region = from_direction.name
            state.row_synced[region] = True
            if packet.has_value and packet.value is not None:
                if state.row_values[region] is None:
                    state.row_values[region] = packet.value
                else:
                    state.row_values[region] = min(state.row_values[region],
                                                   packet.value)

        logger.debug(f'{self.clock.cycle}: SYNC_RECV: synchronizer ({self.x},{self.y}) '
                     f'from={from_direction.name} sync_ident={sync_ident} '
                     f'value={packet.value}')
        self._notify_if_complete(sync_ident)

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
                    byte_val = in_buf.popleft()
                    partial.append(byte_val)

                    # Check if we have a complete packet
                    if len(partial) >= 1:
                        has_value = (partial[0] & 0x80) != 0
                        expected_len = 5 if has_value else 1

                        if len(partial) >= expected_len:
                            packet = SyncPacket.from_bytes(bytes(partial[:expected_len]))
                            self._process_received_packet(packet, direction)
                            del partial[:expected_len]

            # Continue sending any packets in progress (one byte per direction per cycle)
            for direction in SyncDirection:
                if direction in self._outgoing_packets and self._outgoing_packets[direction]:
                    out_buf = self._output_buffers[direction]
                    if out_buf.can_append():
                        byte_val = self._outgoing_packets[direction].pop(0)
                        out_buf.append(byte_val)
                        if not self._outgoing_packets[direction]:
                            del self._outgoing_packets[direction]

            # Start new packets if we should send and no packet in progress for that direction
            for state in list(self._sync_states.values()):
                for direction in SyncDirection:
                    if direction not in self._outgoing_packets and self._should_send(state, direction):
                        value = self._get_min_for_direction(state, direction)
                        packet = SyncPacket(
                            sync_ident=state.sync_ident,
                            has_value=state.has_value,
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
                self._notify_if_complete(state.sync_ident)

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

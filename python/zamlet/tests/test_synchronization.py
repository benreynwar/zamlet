"""
Test for the lamlet-wide synchronization network.

Creates a grid of Synchronizers that communicate with each other.
Randomly creates sync events, triggers them on each synchronizer at different times,
and verifies that all synchronizers eventually know that everyone has seen each event.
"""

import logging
import asyncio
import random

import pytest

from zamlet.synchronization import Synchronizer, SyncDirection
from zamlet.runner import Clock


logger = logging.getLogger(__name__)


class MockMonitor:
    """Mock monitor for sync tests."""
    def __init__(self):
        # Track which (sync_ident, x, y) have completed and their min values
        self.completed = {}  # (sync_ident, x, y) -> min_value

    def record_sync_local_event(self, sync_ident, x, y, value):
        pass

    def record_sync_local_complete(self, sync_ident, x, y, min_value):
        self.completed[(sync_ident, x, y)] = min_value


# Map from direction to opposite direction (for wiring neighbors)
OPPOSITE_DIRECTION = {
    SyncDirection.N: SyncDirection.S,
    SyncDirection.S: SyncDirection.N,
    SyncDirection.E: SyncDirection.W,
    SyncDirection.W: SyncDirection.E,
    SyncDirection.NE: SyncDirection.SW,
    SyncDirection.SW: SyncDirection.NE,
    SyncDirection.NW: SyncDirection.SE,
    SyncDirection.SE: SyncDirection.NW,
}


class SyncNetwork:
    """A grid of synchronizers wired together, including the lamlet at (0, -1)."""

    def __init__(self, clock, cols: int, rows: int):
        self.clock = clock
        self.cols = cols
        self.rows = rows

        # Create a minimal params-like object with just what Synchronizer needs
        class SyncParams:
            def __init__(self, cols, rows):
                self.k_cols = cols
                self.k_rows = rows
                self.j_cols = 1
                self.j_rows = 1

        self.params = SyncParams(cols, rows)
        self.monitor = MockMonitor()

        # Create grid of synchronizers
        self.synchronizers = {}
        for y in range(rows):
            for x in range(cols):
                self.synchronizers[(x, y)] = Synchronizer(
                    clock, self.params, x, y, None, self.monitor)

        # Add lamlet synchronizer at (0, -1)
        self.synchronizers[(0, -1)] = Synchronizer(
            clock, self.params, 0, -1, None, self.monitor)

    def get_neighbor_coords(self, x: int, y: int, direction: SyncDirection):
        """Get coordinates of neighbor in given direction, or None if no neighbor."""
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
        dx, dy = deltas[direction]
        nx, ny = x + dx, y + dy
        # Check if neighbor exists in our synchronizers map
        if (nx, ny) in self.synchronizers:
            return (nx, ny)
        return None

    async def run_network(self):
        """Transfer bytes between neighbors each cycle."""
        while True:
            await self.clock.next_cycle

            # For each synchronizer, check outputs and deliver to neighbors
            for (x, y), sync in self.synchronizers.items():
                for direction in SyncDirection:
                    if sync.has_output(direction):
                        neighbor_coords = self.get_neighbor_coords(x, y, direction)
                        if neighbor_coords:
                            neighbor = self.synchronizers[neighbor_coords]
                            opposite = OPPOSITE_DIRECTION[direction]
                            # Only transfer if neighbor has room
                            if neighbor.can_receive(opposite):
                                byte_val = sync.get_output(direction)
                                if byte_val is not None:
                                    neighbor.receive(opposite, byte_val)

    async def run_updates(self):
        """Update all synchronizer buffers each cycle."""
        while True:
            await self.clock.next_update
            for sync in self.synchronizers.values():
                sync.update()


async def run_sync_test(clock, cols: int, rows: int, n_events: int, seed: int):
    """
    Run the synchronization test.

    Args:
        clock: The simulation clock
        cols: Number of columns in the grid
        rows: Number of rows in the grid
        n_events: Number of sync events to test
        seed: Random seed for reproducibility
    """
    rnd = random.Random(seed)
    network = SyncNetwork(clock, cols, rows)

    # Start all synchronizer run loops
    for sync in network.synchronizers.values():
        clock.create_task(sync.run())

    # Start network transfer loop
    clock.create_task(network.run_network())
    clock.create_task(network.run_updates())

    # Generate random event schedules
    # For each ident: pick a start time and duration, trigger events randomly within that window
    # Windows can overlap between different idents
    # Each synchronizer gets a random value; we'll verify the minimum is computed correctly
    event_schedules = {}  # sync_ident -> [(cycle, coord, value), ...]
    last_trigger_cycle = {}  # sync_ident -> cycle of last event
    expected_min = {}  # sync_ident -> expected minimum value
    all_values = {}
    for sync_ident in range(n_events):
        start_time = rnd.randint(0, 50)
        duration = rnd.randint(5, 20)
        schedule = []
        values = []
        values_map = {}
        for coord in network.synchronizers.keys():
            trigger_cycle = start_time + rnd.randint(0, duration)
            value = rnd.randint(1, 1000)
            schedule.append((trigger_cycle, coord, value))
            values.append(value)
            values_map[coord] = value
        event_schedules[sync_ident] = schedule
        last_trigger_cycle[sync_ident] = max(cycle for cycle, _, _ in schedule)
        expected_min[sync_ident] = min(values)
        all_values[sync_ident] = values_map

    # Track when first/last synchronizer thinks each event is complete
    first_complete_cycle = {}  # sync_ident -> cycle when first sync thinks complete
    last_complete_cycle = {}   # sync_ident -> cycle when last sync thinks complete

    # Expected propagation delay after last event
    max_propagation_delay = (cols + rows) * 5 + 10

    # Find when simulation should end
    max_last_trigger = max(last_trigger_cycle.values())
    max_cycle = max_last_trigger + max_propagation_delay + 50

    # Main test loop
    while clock.cycle < max_cycle:
        await clock.next_cycle
        cycle = clock.cycle

        # Trigger events according to schedule
        for sync_ident, schedule in event_schedules.items():
            for trigger_cycle, coord, value in schedule:
                if trigger_cycle == cycle:
                    sync = network.synchronizers[coord]
                    sync.local_event(sync_ident, value=value)
                    logger.debug(f'Cycle {cycle}: Triggered event {sync_ident} on {coord} '
                                 f'value={value}')

        # Check synchronization status
        for sync_ident in range(n_events):
            if sync_ident in last_complete_cycle:
                continue  # Already fully complete

            any_thinks_complete = False
            all_think_complete = True

            for (x, y) in network.synchronizers.keys():
                if (sync_ident, x, y) in network.monitor.completed:
                    any_thinks_complete = True
                else:
                    all_think_complete = False

            # Track when first synchronizer thinks complete
            if any_thinks_complete and sync_ident not in first_complete_cycle:
                first_complete_cycle[sync_ident] = cycle
                logger.info(f'Cycle {cycle}: First sync thinks event {sync_ident} complete')

            # Track when last synchronizer thinks complete
            if all_think_complete:
                last_complete_cycle[sync_ident] = cycle
                logger.info(f'Cycle {cycle}: All syncs think event {sync_ident} complete')

    # Verify invariants
    for sync_ident in range(n_events):
        last_trigger = last_trigger_cycle[sync_ident]

        # INVARIANT 1: No one should think complete before the cycle when last trigger fired
        # (can be complete on the same cycle since we check after triggering)
        if sync_ident not in first_complete_cycle:
            raise AssertionError(
                f'Event {sync_ident}: completed but never had a first_complete_cycle'
            )
        first_complete = first_complete_cycle[sync_ident]
        if first_complete < last_trigger:
            raise AssertionError(
                f'Event {sync_ident}: first sync thought complete at cycle {first_complete} '
                f'but last trigger was at cycle {last_trigger}'
            )

        # INVARIANT 2: All should think complete within max_propagation_delay of last trigger
        if sync_ident not in last_complete_cycle:
            logger.error(f'Event {sync_ident} not complete by end of simulation')
            for (x, y), sync in network.synchronizers.items():
                if not sync.is_complete(sync_ident):
                    state = sync._sync_states.get(sync_ident)
                    if state:
                        logger.error(f'  Sync ({x},{y}): local_seen={state.local_seen} '
                                     f'quad={state.quadrant_synced} '
                                     f'col={state.column_synced} '
                                     f'row={state.row_synced}')
            raise AssertionError(f'Event {sync_ident} did not complete')

        last_complete = last_complete_cycle[sync_ident]
        delay = last_complete - last_trigger
        logger.info(f'Event {sync_ident}: last_trigger={last_trigger}, '
                    f'first_complete={first_complete}, '
                    f'last_complete={last_complete}, delay={delay}')
        if delay > max_propagation_delay:
            raise AssertionError(
                f'Event {sync_ident} took too long to propagate: {delay} cycles'
            )

        # INVARIANT 3: All synchronizers should agree on the minimum value
        expected = expected_min[sync_ident]
        for (x, y) in network.synchronizers.keys():
            actual = network.monitor.completed[(sync_ident, x, y)]
            if actual != expected:
                raise AssertionError(
                    f'Event {sync_ident}: sync ({x},{y}) has min={actual}, expected={expected}'
                )
        logger.info(f'Event {sync_ident}: min value correct = {expected}')

    logger.info('SUCCESS!')


async def main(clock, cols, rows, n_events, seed):
    clock.register_main()
    clock_driver_task = clock.create_task(clock.clock_driver())
    await run_sync_test(clock, cols, rows, n_events, seed)
    clock.running = False


def run_test(cols: int, rows: int, n_events: int, seed: int, max_cycles: int = 2000):
    """Helper to run a single test configuration."""
    clock = Clock(max_cycles=max_cycles)
    asyncio.run(main(clock, cols, rows, n_events, seed))


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for cols in [2, 4]:
        for rows in [2, 4]:
            for n_events in [3, 5]:
                for seed in [42, 123]:
                    id_str = f"{cols}x{rows}_events{n_events}_seed{seed}"
                    params.append(pytest.param(cols, rows, n_events, seed, id=id_str))
    return params


@pytest.mark.parametrize("cols,rows,n_events,seed", generate_test_params())
def test_synchronization(cols, rows, n_events, seed):
    run_test(cols, rows, n_events, seed)


if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Test synchronization network')
    parser.add_argument('--cols', type=int, default=4, help='Grid columns')
    parser.add_argument('--rows', type=int, default=4, help='Grid rows')
    parser.add_argument('--events', type=int, default=5, help='Number of sync events')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--max-cycles', type=int, default=2000, help='Max simulation cycles')
    parser.add_argument('--log-level', default='INFO', help='Logging level')
    args = parser.parse_args()

    level = getattr(logging, args.log_level.upper())
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    root_logger.info(f'Starting test: {args.cols}x{args.rows} grid, {args.events} events, seed={args.seed}')
    clock = Clock(max_cycles=args.max_cycles)
    asyncio.run(main(clock, args.cols, args.rows, args.events, args.seed))

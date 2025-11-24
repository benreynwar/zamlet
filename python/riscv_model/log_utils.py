'''
This is utilities that analyze the log and write summaries of what is happening.
'''
import re
from collections import defaultdict


def print_cache_allocation_table(logfile_path):
    """
    Parse log file and print a table showing cache line allocations.

    Shows which memory_loc is allocated to which slot in each kamlet cache table,
    organized by cycle. This helps track cache evictions and reallocations.

    Args:
        logfile_path: Path to the log file to analyze
    """
    allocations = []

    with open(logfile_path, 'r') as f:
        for line in f:
            if 'CACHE_LINE_ALLOC:' in line:
                match = re.search(
                    r'(\d+): CACHE_LINE_ALLOC: CacheTable \((\d+), (\d+)\) '
                    r'slot=(\d+) memory_loc=(0x[0-9a-f]+)',
                    line
                )
                if match:
                    cycle = int(match.group(1))
                    kamlet_x = match.group(2)
                    kamlet_y = match.group(3)
                    slot = int(match.group(4))
                    mem_loc = int(match.group(5), 16)

                    allocations.append({
                        'cycle': cycle,
                        'kamlet': f'({kamlet_x},{kamlet_y})',
                        'slot': slot,
                        'mem_loc': mem_loc
                    })

    if not allocations:
        print("No cache line allocations found in log")
        return

    print("=" * 100)
    print("CACHE LINE ALLOCATION TABLE")
    print("=" * 100)
    print(f"{'Cycle':<10} {'Kamlet':<12} {'Slot':<8} {'Memory Loc':<15} {'Notes':<30}")
    print("-" * 100)

    slot_history = defaultdict(list)

    for alloc in allocations:
        kamlet = alloc['kamlet']
        slot = alloc['slot']
        mem_loc = alloc['mem_loc']
        cycle = alloc['cycle']

        key = (kamlet, slot)
        notes = ""

        if key in slot_history:
            prev_mem_loc = slot_history[key][-1]
            if prev_mem_loc != mem_loc:
                notes = f"EVICT (was 0x{prev_mem_loc:x})"

        slot_history[key].append(mem_loc)

        print(f"{cycle:<10} {kamlet:<12} {slot:<8} 0x{mem_loc:<13x} {notes:<30}")

    print("=" * 100)
    print(f"\nTotal allocations: {len(allocations)}")
    reallocations = sum(1 for hist in slot_history.values() if len(hist) > 1)
    print(f"Reallocations (evictions): {reallocations}")


def print_cache_allocations_for_address_range(logfile_path, start_addr, end_addr):
    """
    Print cache allocations for a specific global address range.

    First finds which memory_loc range the global address maps to via PAGE_ALLOC,
    then shows all cache line allocations for those memory_locs.

    Args:
        logfile_path: Path to the log file
        start_addr: Starting global address (e.g., 0x20000000)
        end_addr: Ending global address (e.g., 0x200003ff)
    """
    mem_loc_start = None
    mem_loc_end = None

    with open(logfile_path, 'r') as f:
        for line in f:
            if 'PAGE_ALLOC:' in line:
                match = re.search(
                    r'PAGE_ALLOC: global=(0x[0-9a-f]+)-(0x[0-9a-f]+) -> '
                    r'physical=(0x[0-9a-f]+) memory_loc=(0x[0-9a-f]+)-(0x[0-9a-f]+)',
                    line
                )
                if match:
                    global_start = int(match.group(1), 16)
                    global_end = int(match.group(2), 16)

                    if global_start == start_addr and global_end == end_addr:
                        mem_loc_start = int(match.group(4), 16)
                        mem_loc_end = int(match.group(5), 16)
                        print(f"Found page: global=0x{global_start:x}-0x{global_end:x} "
                              f"-> memory_loc=0x{mem_loc_start:x}-0x{mem_loc_end:x}")
                        break

    if mem_loc_start is None:
        print(f"No page allocation found for 0x{start_addr:x}-0x{end_addr:x}")
        return

    allocations = []
    with open(logfile_path, 'r') as f:
        for line in f:
            if 'CACHE_LINE_ALLOC:' in line:
                match = re.search(
                    r'(\d+): CACHE_LINE_ALLOC: CacheTable \((\d+), (\d+)\) '
                    r'slot=(\d+) memory_loc=(0x[0-9a-f]+)',
                    line
                )
                if match:
                    cycle = int(match.group(1))
                    kamlet_x = match.group(2)
                    kamlet_y = match.group(3)
                    slot = int(match.group(4))
                    mem_loc = int(match.group(5), 16)

                    if mem_loc_start <= mem_loc <= mem_loc_end:
                        allocations.append({
                            'cycle': cycle,
                            'kamlet': f'({kamlet_x},{kamlet_y})',
                            'slot': slot,
                            'mem_loc': mem_loc
                        })

    print("\n" + "=" * 100)
    print(f"CACHE ALLOCATIONS FOR GLOBAL 0x{start_addr:x}-0x{end_addr:x}")
    print(f"(memory_loc range: 0x{mem_loc_start:x}-0x{mem_loc_end:x})")
    print("=" * 100)
    print(f"{'Cycle':<10} {'Kamlet':<12} {'Slot':<8} {'Memory Loc':<15}")
    print("-" * 100)

    for alloc in allocations:
        print(f"{alloc['cycle']:<10} {alloc['kamlet']:<12} {alloc['slot']:<8} "
              f"0x{alloc['mem_loc']:<13x}")

    print("=" * 100)
    print(f"Total allocations in this range: {len(allocations)}")

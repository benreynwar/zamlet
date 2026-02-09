"""
Pytest tests for the bitreverse reorder kernel.
"""

import dataclasses
import os

import matplotlib.pyplot as plt
import pytest

from zamlet.addresses import WordOrder
from zamlet.geometries import GEOMETRIES,  SMALL_GEOMETRIES
from zamlet.kernel_tests.conftest import build_if_needed, run_kernel
from zamlet.monitor import SpanType
from zamlet.analysis.plot_network import plot_network
from zamlet.analysis.plot_queues import dump_queue_table, plot_queues
from zamlet.tests.test_utils import dump_span_trees


KERNEL_DIR = os.path.dirname(__file__)


def compute_n(params):
    """Compute n (number of elements) from geometry params for e32."""
    j_in_l = params.k_cols * params.k_rows * params.j_cols * params.j_rows
    vl = j_in_l * params.word_bytes // 4  # e32
    return 8 * vl


def bitreverse_symbol_values(params, reverse_bits=None,
                             skip_verify=False):
    """Compute symbol_values for the bitreverse kernel."""
    n = compute_n(params)
    if reverse_bits is None:
        reverse_bits = n.bit_length() - 1
    values = {'n': n, 'reverse_bits': reverse_bits}
    if skip_verify:
        values['skip_verify'] = 1
    return values


def measure_indexed_load_batches(monitor, batch_size=8):
    """Measure cycles between batches of indexed loads on kamlet(0,0).

    Finds all LoadIndexedUnordered KINSTR_EXEC spans on kamlet(0,0),
    groups them into batches of batch_size, and reports the completed_cycle
    of the first span in each batch.

    Returns list of batch start cycles (completed_cycle of first span
    in each batch).
    """
    spans = [
        s for s in monitor.spans.values()
        if s.span_type == SpanType.KINSTR_EXEC
        and s.details.get('instr_type') == 'LoadIndexedUnordered'
        and s.details.get('kamlet_x') == 0
        and s.details.get('kamlet_y') == 0
    ]
    spans.sort(key=lambda s: s.created_cycle)
    n_batches = len(spans) // batch_size
    print(f"Found {len(spans)} indexed loads on kamlet(0,0), "
          f"{n_batches} batches of {batch_size}")
    batch_cycles = []
    for i in range(n_batches):
        first = spans[i * batch_size]
        batch_cycles.append(first.completed_cycle)
        print(f"  Batch {i}: cycle {first.completed_cycle}")
    if n_batches >= 4:
        b1 = spans[1 * batch_size].completed_cycle
        b3 = spans[3 * batch_size].completed_cycle
        print(f"Batch 2 end to batch 4 end: {b3 - b1} cycles")
    return batch_cycles


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for geom_name, geom_params in SMALL_GEOMETRIES.items():
        id_str = f"bitreverse_{geom_name}"
        params.append(pytest.param(geom_params, id=id_str))
    return params


@pytest.mark.parametrize("params", generate_test_params())
def test_bitreverse(params):
    """Run bitreverse kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'bitreverse-reorder.riscv')
    sv = bitreverse_symbol_values(params)
    exit_code, _monitor = run_kernel(binary_path, params=params,
                                     symbol_values=sv)
    assert exit_code == 0, f"Kernel failed with exit code {exit_code}"


@pytest.mark.parametrize("params", generate_test_params())
def test_bitreverse64(params):
    """Run 64-bit bitreverse kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'bitreverse-reorder64.riscv')
    sv = bitreverse_symbol_values(params)
    exit_code, _monitor = run_kernel(binary_path, params=params,
                                     symbol_values=sv)
    assert exit_code == 0, f"Kernel failed with exit code {exit_code}"


if __name__ == '__main__':
    import argparse
    import logging

    parser = argparse.ArgumentParser(description='Run bitreverse reorder test')
    parser.add_argument('-g', '--geometry', default='k2x1_j1x2',
                        help='Geometry name (default: k2x1_j1x2)')
    parser.add_argument('--e64', action='store_true',
                        help='Run 64-bit element width version')
    parser.add_argument('--list-geometries', action='store_true',
                        help='List available geometries')
    parser.add_argument('--log-level', default='WARNING',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Log level (default: WARNING)')
    parser.add_argument('--max-cycles', type=int, default=100000,
                        help='Maximum simulation cycles (default: 100000)')
    parser.add_argument('--moore', action='store_true',
                        help='Use Moore curve word order')
    parser.add_argument('--skip-verify', action='store_true',
                        help='Skip result verification in the kernel')
    parser.add_argument('--reverse-bits', type=int, default=None,
                        help='Number of bits to reverse (default: clog2(n))')
    args = parser.parse_args()

    if args.list_geometries:
        print("Available geometries:")
        for name in GEOMETRIES:
            print(f"  {name}")
    else:
        logging.basicConfig(level=getattr(logging, args.log_level), format='%(message)s')

        if args.geometry not in GEOMETRIES:
            print(f"Unknown geometry: {args.geometry}")
            print("Use --list-geometries to see available options")
            exit(1)

        params = dataclasses.replace(GEOMETRIES[args.geometry], jamlet_sram_bytes=1 << 10)
        word_order = WordOrder.MOORE if args.moore else WordOrder.STANDARD
        binary_name = 'bitreverse-reorder64.riscv' if args.e64 else 'bitreverse-reorder.riscv'
        binary_path = build_if_needed(KERNEL_DIR, binary_name)
        sv = bitreverse_symbol_values(
            params, reverse_bits=args.reverse_bits,
            skip_verify=args.skip_verify)
        exit_code, monitor = run_kernel(
            binary_path, params=params, max_cycles=args.max_cycles,
            word_order=word_order, symbol_values=sv)
        print(f"Exit code: {exit_code}, cycles: {monitor.clock.cycle}")
        batch_cycles = measure_indexed_load_batches(monitor)

        span_trees_path = os.path.join(KERNEL_DIR, 'span_trees.txt')
        dump_span_trees(monitor, span_trees_path)
        print(f"Span trees written to {span_trees_path}")

        ts = monitor.get_router_utilization_timeseries()
        if ts:
            window = 50
            n_windows = len(ts) // window
            cycles = []
            pct_occupied = []
            pct_moving = []
            for w in range(n_windows):
                chunk = ts[w * window:(w + 1) * window]
                cycles.append(sum(t[0] for t in chunk) / window)
                pct_occupied.append(sum(t[1] for t in chunk) / window)
                pct_moving.append(sum(t[2] for t in chunk) / window)

            suffix = '64' if args.e64 else '32'
            title = (f"Bitreverse e{suffix} - {args.geometry}"
                     f" ({monitor.clock.cycle} cycles)")

            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(cycles, pct_occupied, label='% occupied', alpha=0.8)
            ax.plot(cycles, pct_moving, label='% moving', alpha=0.8)
            ax.set_xlabel('Cycle')
            ax.set_ylabel('% of connections')
            ax.set_title(title)
            ax.legend()
            ax.set_ylim(0, 100)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            output_path = os.path.join(
                KERNEL_DIR, f"utilization_e{suffix}_{args.geometry}.png")
            fig.savefig(output_path, dpi=150)
            print(f"Plot saved to {output_path}")

        suffix = '64' if args.e64 else '32'
        base = f"e{suffix}_{args.geometry}"
        title = (f"Bitreverse e{suffix} - {args.geometry}"
                 f" ({monitor.clock.cycle} cycles)")

        plot_path = os.path.join(
            KERNEL_DIR, f"queues_{base}.png")
        plot_queues(monitor, plot_path, title=title,
                    cycle_min=7500, cycle_max=10000)
        print(f"Queue plot saved to {plot_path}")

        table_path = os.path.join(
            KERNEL_DIR, f"queues_{base}.tsv")
        dump_queue_table(monitor, table_path,
                         cycle_min=7500, cycle_max=10000)
        print(f"Queue table saved to {table_path}")

        assert len(batch_cycles) >= 4, \
            f"Need at least 4 batches for network images, got {len(batch_cycles)}"
        window = 50
        net_start = batch_cycles[0] // window * window
        net_end = (batch_cycles[3] + window - 1) // window * window
        network_dir = os.path.join(KERNEL_DIR, f"network_{base}")
        os.makedirs(network_dir, exist_ok=True)
        for c_min in range(net_start, net_end, window):
            c_max = c_min + window
            net_title = (f"Bitreverse e{suffix} - {args.geometry}"
                         f"  cycles {c_min}-{c_max}")
            net_path = os.path.join(
                network_dir, f"{c_min}_{c_max}.png")
            plot_network(monitor, net_path, title=net_title,
                         cycle_min=c_min, cycle_max=c_max)
        print(f"Network plots saved to {network_dir}/")

        exit(exit_code)

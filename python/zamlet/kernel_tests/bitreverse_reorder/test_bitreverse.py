"""
Pytest tests for the bitreverse reorder kernel.
"""

import dataclasses
import os

import matplotlib.pyplot as plt
import pytest

from zamlet.geometries import GEOMETRIES
from zamlet.kernel_tests.conftest import build_if_needed, run_kernel
from zamlet.analysis.plot_network import plot_network
from zamlet.analysis.plot_queues import dump_queue_table, plot_queues
from zamlet.tests.test_utils import dump_span_trees


KERNEL_DIR = os.path.dirname(__file__)


def generate_test_params():
    """Generate test parameter combinations."""
    params = []
    for geom_name, geom_params in GEOMETRIES.items():
        id_str = f"bitreverse_{geom_name}"
        params.append(pytest.param(geom_params, id=id_str))
    return params


@pytest.mark.parametrize("params", generate_test_params())
def test_bitreverse(params):
    """Run bitreverse kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'bitreverse-reorder.riscv')
    exit_code, _monitor = run_kernel(binary_path, params=params)
    assert exit_code == 0, f"Kernel failed with exit code {exit_code}"


@pytest.mark.parametrize("params", generate_test_params())
def test_bitreverse64(params):
    """Run 64-bit bitreverse kernel and verify it passes."""
    binary_path = build_if_needed(KERNEL_DIR, 'bitreverse-reorder64.riscv')
    exit_code, _monitor = run_kernel(binary_path, params=params)
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
        binary_name = 'bitreverse-reorder64.riscv' if args.e64 else 'bitreverse-reorder.riscv'
        binary_path = build_if_needed(KERNEL_DIR, binary_name)
        exit_code, monitor = run_kernel(binary_path, params=params, max_cycles=args.max_cycles)
        print(f"Exit code: {exit_code}, cycles: {monitor.clock.cycle}")

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
                    cycle_min=41500, cycle_max=43000)
        print(f"Queue plot saved to {plot_path}")

        table_path = os.path.join(
            KERNEL_DIR, f"queues_{base}.tsv")
        dump_queue_table(monitor, table_path,
                         cycle_min=41500, cycle_max=43000)
        print(f"Queue table saved to {table_path}")

        network_dir = os.path.join(KERNEL_DIR, f"network_{base}")
        os.makedirs(network_dir, exist_ok=True)
        window = 50
        net_start = 41700
        net_end = 42900
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

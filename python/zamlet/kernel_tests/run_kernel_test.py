"""Generic kernel test runner for Bazel py_test targets.

Reads configuration from environment variables set by the kernel_test macro:
  KERNEL_BINARY: path to the .riscv ELF binary
  GEOMETRY: geometry name (e.g. "k2x1_j1x1")
  MAX_CYCLES: maximum simulation cycles (default 100000)
  EXPECTED_FAILURE: "1" if the kernel should fail, "0" otherwise
"""
import asyncio
import logging
import os
import sys

from zamlet.geometries import get_geometry
from zamlet.runner import Clock
from zamlet.oamlet.run_oamlet import main as run_lamlet_main


def main():
    log_level = os.environ.get("LOG_LEVEL", "WARNING")
    logging.basicConfig(level=getattr(logging, log_level), stream=sys.stderr)
    binary = os.environ["KERNEL_BINARY"]
    geometry = get_geometry(os.environ["GEOMETRY"])
    max_cycles = int(os.environ.get("MAX_CYCLES", "100000"))
    expected_failure = os.environ.get("EXPECTED_FAILURE", "0") == "1"

    clock = Clock(max_cycles=max_cycles)
    exit_code, _monitor = asyncio.run(run_lamlet_main(clock, binary, geometry))

    if expected_failure:
        assert exit_code != 0, f"Kernel {binary} should have failed but returned 0"
    else:
        assert exit_code == 0, f"Kernel {binary} failed with exit code {exit_code}"


if __name__ == "__main__":
    main()

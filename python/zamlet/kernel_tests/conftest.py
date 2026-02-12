"""
Pytest configuration for kernel tests.

Provides fixtures and utilities for running RISC-V binaries through run_lamlet.
"""

import asyncio
import os
import subprocess
import logging

import pytest

from zamlet.addresses import WordOrder
from zamlet.runner import Clock
from zamlet.oamlet.run_oamlet import main as run_lamlet_main

logger = logging.getLogger(__name__)


def build_if_needed(kernel_dir: str, binary_name: str) -> str:
    """
    Build the RISC-V binary if it doesn't exist.

    Args:
        kernel_dir: Path to the kernel test directory (e.g., 'kernel_tests/conditional')
        binary_name: Name of the binary file (e.g., 'vec-conditional.riscv')

    Returns:
        Full path to the binary file

    Raises:
        FileNotFoundError: If build script doesn't exist
        subprocess.CalledProcessError: If build fails
    """
    binary_path = os.path.join(kernel_dir, binary_name)

    if os.path.exists(binary_path):
        return binary_path

    # Find build script
    build_scripts = [
        f for f in os.listdir(kernel_dir)
        if f.startswith('build') and f.endswith('.sh')
    ]

    if not build_scripts:
        raise FileNotFoundError(f"No build script found in {kernel_dir}")

    build_script = os.path.join(kernel_dir, build_scripts[0])
    logger.info(f"Building {binary_name} using {build_script}")

    # Run build script from the kernel directory
    result = subprocess.run(
        ['bash', build_scripts[0]],
        cwd=kernel_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"Build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
        raise subprocess.CalledProcessError(
            result.returncode, build_script, result.stdout, result.stderr
        )

    if not os.path.exists(binary_path):
        raise FileNotFoundError(
            f"Build script ran but {binary_path} was not created. "
            f"stdout: {result.stdout}"
        )

    return binary_path


def run_kernel(binary_path: str, params=None, max_cycles: int = 100000,
               word_order: WordOrder = WordOrder.STANDARD,
               symbol_values: dict = None):
    """
    Run a RISC-V binary through run_lamlet.

    Args:
        binary_path: Path to the .riscv binary
        params: ZamletParams configuration (uses default if None)
        max_cycles: Maximum simulation cycles
        word_order: Word order for VPU memory layout
        symbol_values: Dict of {symbol_name: int32_value} to set before
            execution. Overwrites volatile globals in the ELF.

    Returns:
        (exit_code, monitor) tuple
    """
    clock = Clock(max_cycles=max_cycles)
    exit_code, monitor = asyncio.run(
        run_lamlet_main(clock, binary_path, params, word_order,
                        symbol_values))
    return exit_code, monitor

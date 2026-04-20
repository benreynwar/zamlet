# Plan: Test scalar reads from VPU memory

## Motivation

The `vecadd_evict` kernel test fails because element[1] at address 0x900c0004 reads back
as 1100 instead of 1101 via scalar `lwu`. Both elements 0 and 1 return the same value.
The register future/blocking mechanism works correctly -- the bug is in the data path.

We need a Python model test (not a kernel test) that isolates whether:
- `set_memory` and `get_memory` agree on VPU address mapping (scalar write + scalar read)
- `vstore` and `get_memory` agree on VPU address mapping (vector write + scalar read)

## Test file

`python/zamlet/tests/test_scalar_read_vpu.py`

## Sub-tests

### 1. set_memory round-trip

Write known sequential values (e.g., 1100, 1101, 1102, ...) to VPU memory one element at a
time via `lamlet.set_memory`, then read each element back via `lamlet.get_memory`. Verify
each element matches.

This tests the scalar-only address mapping round-trip. If this fails, the bug is in the
address translation used by `set_memory`/`get_memory`.

### 2. vstore then get_memory

Load sequential values into a vector register (write to VPU via `set_memory`, then `vload`),
then `vstore` to a different VPU region, then read each element back via `get_memory`. Verify
each element matches.

This tests the vector-write + scalar-read cross-path. If sub-test 1 passes but this fails,
the bug is in how `vstore` and `get_memory` disagree on element placement.

### 3. vstore then set_memory round-trip (control)

Same as sub-test 2 but also read back via `vload` into a different register, then `vstore`
to a third region, then `get_memory` from that third region. This confirms the vstore path
is self-consistent.

## Parameters

- Geometries: SMALL_GEOMETRIES (k2x1_j1x1, k2x1_j1x2, k2x1_j2x1, etc.)
- Element widths: 32 (start here since that's the failing case; extend to 8, 16, 64)
- VL: use a small count like 8 elements (enough to span multiple kamlets)
- Values: sequential starting from 1100 to match the kernel test pattern

## Test structure

Use the existing test infrastructure from `tests/test_utils.py`:
- `setup_lamlet` for creating the lamlet
- `pack_elements` / `unpack_elements` for data conversion
- `get_vpu_base_addr` for base addresses

Use two separate VPU memory regions (different pages) for source and destination so that
vload/vstore don't alias.

## Implementation steps

1. Create `test_scalar_read_vpu.py` with the test harness (setup, teardown, parametrize).
2. Implement sub-test 1: `set_memory` round-trip.
3. Implement sub-test 2: `vstore` then `get_memory`.
4. Implement sub-test 3 (control): full vector round-trip.
5. Run with k2x1_j1x1 ew=32 first to reproduce the failure pattern.
6. If a sub-test fails, use the failure to narrow down which address translation path
   disagrees.

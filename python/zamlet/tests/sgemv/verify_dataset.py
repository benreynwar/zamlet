#!/usr/bin/env python3
"""
Verify that the dataset_64x64.h file contains correct expected results.
"""

import numpy as np
import re

def parse_dataset(filename):
    """Parse the C header file to extract M_DIM, N_DIM, matrix A, vector x, and verify_data."""
    with open(filename, 'r') as f:
        content = f.read()

    # Extract M_DIM and N_DIM
    m_match = re.search(r'#define M_DIM (\d+)', content)
    n_match = re.search(r'#define N_DIM (\d+)', content)
    m_dim = int(m_match.group(1))
    n_dim = int(n_match.group(1))

    print(f"M_DIM = {m_dim}, N_DIM = {n_dim}")

    # Extract input_data_A
    a_match = re.search(r'float input_data_A\[.*?\].*?=\s*\{(.*?)\n\};', content, re.DOTALL)
    if a_match:
        a_str = a_match.group(1)
        # Extract all floating point numbers (including .0)
        a_values = [float(x) for x in re.findall(r'\d+\.?\d*', a_str)]
        A = np.array(a_values).reshape(m_dim, n_dim)
        print(f"Matrix A shape: {A.shape}, total elements: {len(a_values)}")
    else:
        raise ValueError("Could not find input_data_A")

    # Extract input_data_x
    x_match = re.search(r'float input_data_x\[.*?\].*?=\s*\{(.*?)\n\};', content, re.DOTALL)
    if x_match:
        x_str = x_match.group(1)
        x_values = [float(x) for x in re.findall(r'\d+\.?\d*', x_str)]
        x = np.array(x_values)
        print(f"Vector x shape: {x.shape}, total elements: {len(x_values)}")
    else:
        raise ValueError("Could not find input_data_x")

    # Extract verify_data
    v_match = re.search(r'float verify_data\[.*?\].*?=\s*\{(.*?)\n\};', content, re.DOTALL)
    if v_match:
        v_str = v_match.group(1)
        v_values = [float(x) for x in re.findall(r'\d+\.?\d*', v_str)]
        verify = np.array(v_values)
        print(f"Verify data shape: {verify.shape}, total elements: {len(v_values)}")
    else:
        raise ValueError("Could not find verify_data")

    return m_dim, n_dim, A, x, verify

def verify_sgemv(A, x, expected):
    """Verify that x^T @ A equals expected."""
    # SGEMV: y = x^T @ A (vector-matrix multiplication, treating x as a row vector)
    # This is what the assembly does: V^T * M
    computed = x @ A

    print(f"\nComputed result shape: {computed.shape}")
    print(f"Expected result shape: {expected.shape}")

    # Check if they match
    if np.allclose(computed, expected, rtol=1e-5, atol=1e-5):
        print("\n✓ PASS: Computed results match expected results!")
        return True
    else:
        print("\n✗ FAIL: Results do not match!")
        print("\nDifferences:")
        diff = computed - expected
        max_diff_idx = np.argmax(np.abs(diff))
        print(f"Max difference: {diff[max_diff_idx]} at index {max_diff_idx}")
        print(f"  Computed: {computed[max_diff_idx]}")
        print(f"  Expected: {expected[max_diff_idx]}")

        # Show first few mismatches
        mismatches = np.where(~np.isclose(computed, expected, rtol=1e-5, atol=1e-5))[0]
        print(f"\nTotal mismatches: {len(mismatches)}")
        if len(mismatches) > 0:
            print("\nFirst 10 mismatches:")
            for i in mismatches[:10]:
                print(f"  Index {i}: computed={computed[i]:.6f}, "
                      f"expected={expected[i]:.6f}, diff={diff[i]:.6f}")

        return False

if __name__ == "__main__":
    # Verify all datasets
    datasets = ['dataset1.h', 'dataset_large.h', 'dataset_64x64.h']
    all_passed = True

    for dataset_file in datasets:
        print("=" * 80)
        print(f"Verifying {dataset_file}")
        print("=" * 80)

        m_dim, n_dim, A, x, verify = parse_dataset(dataset_file)
        result = verify_sgemv(A, x, verify)
        all_passed = all_passed and result

        if not result:
            print("\nGenerating correct verify_data...")
            computed = x @ A
            print("\nCorrect verify_data values:")
            print("float verify_data[N_DIM] = {")
            # Print in rows of 8 values for readability
            for i in range(0, len(computed), 8):
                row = computed[i:i+8]
                values = ", ".join(f"{v:.1f}" for v in row)
                if i + 8 < len(computed):
                    print(f"  {values},")
                else:
                    print(f"  {values}")
            print("};")

        print()

    print("=" * 80)
    if all_passed:
        print("✓ ALL DATASETS PASSED")
    else:
        print("✗ SOME DATASETS FAILED")
    print("=" * 80)

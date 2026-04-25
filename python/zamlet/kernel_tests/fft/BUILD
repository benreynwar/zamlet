load(":defs.bzl", "fft_n_target", "fft_n_corrupt_target", "fft_n_repeat_target")
load("//bazel:defs.bzl", "SMALL_GEOMETRY_NAMES")

fft_n_target(8)
fft_n_target(16)
fft_n_target(32)
fft_n_target(64, timeout = "long")

# Repeated-FFT timing target: runs the N=64 FFT 4 times in a row with an
# ITER marker before each iteration. Used for per-iteration span analysis.
fft_n_repeat_target(64, repeats = 4, timeout = "long")
fft_n_repeat_target(128, repeats = 2, timeout = "long")
fft_n_repeat_target(256, repeats = 2, geometries = SMALL_GEOMETRY_NAMES + ["k2x2_j4x4"], timeout = "long")
fft_n_repeat_target(1024, repeats = 2, geometries = ["k4x4_j4x4"], timeout = "eternal")

# Sanity negative test: same FFT kernel + wrong expected[]. Must FAIL; guards
# against the test harness vacuously reporting pass.
fft_n_corrupt_target(16)

test_suite(
    name = "all_fft_tests",
    tests = [
        ":test_fftN8",
        ":test_fftN16",
        ":test_fftN32",
        ":test_fftN64",
        ":test_fftN16_corrupt",
    ],
)

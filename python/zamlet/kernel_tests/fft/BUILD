load(":defs.bzl", "fft_n_target", "fft_n_corrupt_target")

fft_n_target(8)
fft_n_target(16)
fft_n_target(32)

# Sanity negative test: same FFT kernel + wrong expected[]. Must FAIL; guards
# against the test harness vacuously reporting pass.
fft_n_corrupt_target(16)

test_suite(
    name = "all_fft_tests",
    tests = [
        ":test_fftN8",
        ":test_fftN16",
        ":test_fftN32",
        ":test_fftN16_corrupt",
    ],
)

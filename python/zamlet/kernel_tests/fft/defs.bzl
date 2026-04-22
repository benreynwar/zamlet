load("//bazel:defs.bzl", "riscv_kernel", "kernel_test")

# vec-fftN: arbitrary-N (power of 2) FFT. One genrule + kernel + test per N.
# The genrule emits a twiddles_N<N>.h containing omega[], seed_block[][], and
# expected[]. `k` bounds the seed_block column count (capped to min(k, N)).
# `max_vlmax` is a compile-time upper bound on vl used to size per-stage tables
# in vec-fftN.c.
#
# corrupt_expected=True builds a sibling target whose expected[] array is
# deliberately wrong, used as an expected-failure sanity check against a
# vacuously-passing test harness.
def _fft_n_kernel_and_test(n, k, max_vlmax, suffix, gen_flags, expected_failure,
                           timeout):
    suffix_label = "{}{}".format(n, suffix)
    twiddles_name = "twiddles_N{}".format(suffix_label)
    kernel_name = "vec-fftN{}".format(suffix_label)
    test_name = "test_fftN{}".format(suffix_label)
    native.genrule(
        name = twiddles_name,
        tools = ["gen_twiddles.py"],
        outs = ["{}.h".format(twiddles_name)],
        cmd = "python3 $(location gen_twiddles.py) {} --k {} {} > $@".format(
            n, k, gen_flags),
    )
    riscv_kernel(
        name = kernel_name,
        srcs = [
            "vec-fftN.c",
            "//python/zamlet/kernel_tests/bitreverse_reorder:compute_indices.c",
            "//python/zamlet/kernel_tests/bitreverse_reorder:bitreverse.S",
            "//python/zamlet/kernel_tests/bitreverse_reorder:bitreverse_reorder64.c",
        ],
        common_srcs = ["//python/zamlet/kernel_tests/common:ara_runtime"],
        hdrs = [
            "//python/zamlet/kernel_tests/common:headers",
            ":" + twiddles_name,
        ],
        linker_script = "//python/zamlet/kernel_tests/common:test.ld",
        copts = [
            "-DPREALLOCATE=1",
            "-ffast-math",
            "-DFFT_N={}".format(n),
            "-DMAX_VLMAX={}".format(max_vlmax),
            "-DTWIDDLE_HEADER=\\\"{}.h\\\"".format(twiddles_name),
            "-I$$(dirname $(location :{}))".format(twiddles_name),
        ],
    )
    kernel_test(
        name = test_name,
        kernel = ":" + kernel_name,
        expected_failure = expected_failure,
        timeout = timeout,
    )


def fft_n_target(n, k = 128, max_vlmax = 64, timeout = "moderate"):
    _fft_n_kernel_and_test(
        n, k, max_vlmax, suffix = "", gen_flags = "",
        expected_failure = False, timeout = timeout)


def fft_n_corrupt_target(n, k = 128, max_vlmax = 64, timeout = "moderate"):
    """Sibling of fft_n_target with a deliberately wrong expected[] array.

    The test passes only if the on-device check reports FAIL, guarding against
    vacuous passes in the normal fft_n_target tests.
    """
    _fft_n_kernel_and_test(
        n, k, max_vlmax, suffix = "_corrupt",
        gen_flags = "--corrupt-expected",
        expected_failure = True, timeout = timeout)

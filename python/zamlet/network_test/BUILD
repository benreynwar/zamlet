load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")
load("//bazel:verilog.bzl", "chisel_verilog")

chisel_verilog(
    name = "packetarbiter_default",
    generator = "//src/main/scala/zamlet/network:packetarbiter",
    config = "//configs:zamlet_default.json",
    extra_args = ["2"],
)

cocotb_binary(
    name = "packetarbiter_default_exe",
    verilog_files = [":packetarbiter_default_verilog"],
    module_top = "PacketArbiter",
)

py_library(
    name = "test_packet_arbiter_py",
    srcs = ["test_packet_arbiter.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_packetarbiter_default",
    binary = ":packetarbiter_default_exe",
    test_module = "zamlet.network_test.test_packet_arbiter",
    toplevel = "PacketArbiter",
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/zamlet_default.json",
    },
    data = ["//configs:zamlet_default.json"],
    py_deps = [":test_packet_arbiter_py"],
)

test_suite(
    name = "all_tests",
    tests = [":test_packetarbiter_default"],
)

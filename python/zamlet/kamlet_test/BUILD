# Kamlet module tests

load("//bazel:cocotb_rules.bzl", "cocotb_binary", "cocotb_test")

# Synchronizer tests
genrule(
    name = "synchronizer_default_verilog",
    srcs = ["//configs:synchronizer_default.json"],
    outs = ["Synchronizer_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/kamlet:synchronizer) $$TMPDIR $(location //configs:synchronizer_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/kamlet:synchronizer"],
)

cocotb_binary(
    name = "synchronizer_default_exe",
    verilog_files = [":synchronizer_default_verilog"],
    module_top = "Synchronizer",
)

py_library(
    name = "test_synchronizer_py",
    srcs = ["test_synchronizer.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_synchronizer_default",
    binary = ":synchronizer_default_exe",
    test_module = "zamlet.kamlet_test.test_synchronizer",
    toplevel = "Synchronizer",
    py_deps = [":test_synchronizer_py"],
)

# KamletMesh tests
genrule(
    name = "kamletmesh_default_verilog",
    srcs = ["//configs:zamlet_default.json"],
    outs = ["KamletMesh_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/kamlet:kamletmesh) $$TMPDIR $(location //configs:zamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/kamlet:kamletmesh"],
)

cocotb_binary(
    name = "kamletmesh_default_exe",
    verilog_files = [":kamletmesh_default_verilog"],
    module_top = "KamletMesh",
)

py_library(
    name = "test_kamlet_py",
    srcs = ["test_kamlet.py"],
    deps = ["//python/zamlet:zamlet"],
)

cocotb_test(
    name = "test_kamlet_default",
    binary = ":kamletmesh_default_exe",
    test_module = "zamlet.kamlet_test.test_kamlet",
    toplevel = "KamletMesh",
    env = {
        "ZAMLET_TEST_CONFIG_FILENAME": "configs/zamlet_default.json",
    },
    data = ["//configs:zamlet_default.json"],
    py_deps = [":test_kamlet_py"],
)

test_suite(
    name = "all_tests",
    tests = [
        # TODO: Re-enable when fixed
        # ":test_synchronizer_default",
        ":test_kamlet_default",
    ],
)

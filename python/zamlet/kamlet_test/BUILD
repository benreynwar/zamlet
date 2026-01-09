# Kamlet module tests

load("//bazel:defs.bzl", "cocotb_exe", "cocotb_script")
load("@rules_hdl//verilog:defs.bzl", "verilog_library")

# ============================================================
# Synchronizer tests
# ============================================================

# Generate Synchronizer verilog using the dedicated generator
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

# Verilog library for bazel_rules_hdl
verilog_library(
    name = "synchronizer_default_verilog_lib",
    srcs = [":synchronizer_default_verilog"],
)

# Cocotb executable
cocotb_exe(
    name = "synchronizer_default_exe",
    verilog_library = ":synchronizer_default_verilog_lib",
    module_top = "Synchronizer",
)

# Test Python library
py_library(
    name = "test_synchronizer_py",
    srcs = ["test_synchronizer.py"],
    imports = ["."],
    deps = [
        "//python/zamlet:zamlet",
        "@zamlet_pip_deps//cocotb",
    ],
)

# Cocotb test script
cocotb_script(
    name = "test_synchronizer_default",
    binary = ":synchronizer_default_exe",
    script = ":test_synchronizer_py",
    module = "test_synchronizer",
    toplevel = "Synchronizer",
)

# ============================================================
# KamletMesh tests (Test 0: instruction receive + sync network)
# ============================================================

# Generate KamletMesh verilog
genrule(
    name = "kamletmesh_default_verilog",
    srcs = ["//configs:lamlet_default.json"],
    outs = ["KamletMesh_default.sv"],
    cmd = """
    TMPDIR=$$(mktemp -d)
    $(location //src/main/scala/zamlet/kamlet:kamletmesh) $$TMPDIR $(location //configs:lamlet_default.json)
    cat $$TMPDIR/*.sv > $@
    rm -rf $$TMPDIR
    """,
    tools = ["//src/main/scala/zamlet/kamlet:kamletmesh"],
)

# Verilog library for bazel_rules_hdl
verilog_library(
    name = "kamletmesh_default_verilog_lib",
    srcs = [":kamletmesh_default_verilog"],
)

# Cocotb executable
cocotb_exe(
    name = "kamletmesh_default_exe",
    verilog_library = ":kamletmesh_default_verilog_lib",
    module_top = "KamletMesh",
)

# Test Python library
py_library(
    name = "test_kamlet_py",
    srcs = ["test_kamlet.py"],
    imports = ["."],
    deps = [
        "//python/zamlet:zamlet",
        "@zamlet_pip_deps//cocotb",
    ],
)

# Cocotb test script
cocotb_script(
    name = "test_kamlet_default",
    binary = ":kamletmesh_default_exe",
    script = ":test_kamlet_py",
    module = "test_kamlet",
    toplevel = "KamletMesh",
)

load("//bazel:cocotb_rules.bzl", "chisel_module_tests", "chisel_module_tests_no_config")
load("//bazel:defs.bzl", "json_file")

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:indextocoordswithreg",
    toplevel = "IndexToCoordsWithReg",
    srcs = ["test_moore.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
        ("16lanes", "//configs:zamlet_16lanes.json"),
        ("64lanes", "//configs:zamlet_64lanes.json"),
        ("1024lanes", "//configs:zamlet_1024lanes.json"),
    ],
    test_modules = [
      ("zamlet.jamlet_test.test_moore", "indextocoordswithreg_test"),
    ],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:coordstoindexwithreg",
    toplevel = "CoordsToIndexWithReg",
    srcs = ["test_moore.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
        ("16lanes", "//configs:zamlet_16lanes.json"),
        ("64lanes", "//configs:zamlet_64lanes.json"),
        ("1024lanes", "//configs:zamlet_1024lanes.json"),
    ],
    test_modules = [
      ("zamlet.jamlet_test.test_moore", "coordstoindexwithreg_test"),
    ],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:jteinitiator",
    toplevel = "JteInitiator",
    srcs = [
        "jteinitiator_driver.py",
        "test_jteinitiator.py",
    ],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = [
      "zamlet.jamlet_test.test_jteinitiator",
    ],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:jamletalu",
    toplevel = "JamletAlu",
    srcs = ["test_jamlet_alu.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = ["zamlet.jamlet_test.test_jamlet_alu"],
)

json_file(
    name = "jamlet_mxu_test_grid_params",
    data = {
        "gridRows": 2,
        "gridCols": 2,
        "mxuN": 2,
        "registerProduct": True,
    },
)

chisel_module_tests_no_config(
    generator = "//src/main/scala/zamlet/jamlet:jamletmxutestgrid",
    toplevel = "JamletMxuTestGrid",
    srcs = ["test_jamlet_mxu.py"],
    generator_args = ["2", "2", "2", "true"],
    config = ":jamlet_mxu_test_grid_params",
    test_modules = ["zamlet.jamlet_test.test_jamlet_mxu"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:jamlet",
    toplevel = "Jamlet",
    srcs = [
        "jamlet_driver.py",
        "test_jamlet.py",
    ],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = ["zamlet.jamlet_test.test_jamlet"],
)

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:localexec",
    toplevel = "LocalExec",
    srcs = ["test_localexec.py"],
    configs = [
        ("default", "//configs:zamlet_default.json"),
    ],
    test_modules = ["zamlet.jamlet_test.test_localexec"],
)

test_suite(
    name = "all_tests",
    tests = [
        ":indextocoordswithreg_tests",
        ":coordstoindexwithreg_tests",
        ":jteinitiator_tests",
        ":jamletalu_tests",
        ":jamletmxutestgrid_tests",
        ":jamlet_tests",
        ":localexec_tests",
    ],
)

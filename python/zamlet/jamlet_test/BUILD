# Jamlet module tests

load("//bazel:cocotb_rules.bzl", "chisel_module_tests")

chisel_module_tests(
    generator = "//src/main/scala/zamlet/jamlet:witemmonitor",
    toplevel = "WitemMonitor",
    srcs = ["test_witem_monitor.py"],
    test_modules = ["zamlet.jamlet_test.test_witem_monitor"],
)

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

test_suite(
    name = "all_tests",
    tests = [":witemmonitor_tests", ":indextocoordswithreg_tests"],
)

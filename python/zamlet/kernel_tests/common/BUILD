package(default_visibility = ["//python/zamlet/kernel_tests:__subpackages__"])

exports_files([
    "crt.S",
    "syscalls.c",
    "test.ld",
    "vpu_alloc.c",
    "util.h",
    "encoding.h",
    "vpu_alloc.h",
    "stdlib.h",
    "stdio.h",
    "string.h",
    "math.h",
    "assert.h",
    "ara/util.c",
    "ara/util.h",
    "ara/gemv.c",
    "ara/gemv.h",
    "ara/fdotproduct.c",
    "ara/fdotproduct.h",
    "ara/exp.h",
    "ara/rivec/vector_defines.h",
])

filegroup(
    name = "standard_runtime",
    srcs = ["crt.S", "syscalls.c"],
)

filegroup(
    name = "ara_runtime",
    srcs = ["crt.S", "syscalls.c", "ara/util.c", "vpu_alloc.c"],
)

filegroup(
    name = "headers",
    srcs = [
        "encoding.h",
        "util.h",
        "vpu_alloc.h",
        "stdlib.h",
        "stdio.h",
        "string.h",
        "math.h",
        "assert.h",
        "ara/exp.h",
        "ara/util.h",
        "ara/gemv.h",
        "ara/fdotproduct.h",
        "ara/rivec/vector_defines.h",
    ],
)

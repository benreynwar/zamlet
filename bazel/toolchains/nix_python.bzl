# Repository rule to find Nix-provided Python for rules_python toolchain

def _find_nix_python_impl(repository_ctx):
    # Watch nix files - when these change, Bazel refetches this repository
    repository_ctx.watch(repository_ctx.path(Label("//:shell.nix")))
    repository_ctx.watch(repository_ctx.path(Label("//nix:common.nix")))

    # Find Python interpreter
    result = repository_ctx.execute(["python3", "-c", "import sys; print(sys.executable)"])
    if result.return_code != 0:
        fail("python3 not found. Are you in nix-shell?")
    python_bin = result.stdout.strip()

    repository_ctx.file("BUILD.bazel", '''
load("@rules_python//python:py_runtime.bzl", "py_runtime")
load("@rules_python//python:py_runtime_pair.bzl", "py_runtime_pair")

py_runtime(
    name = "nix_py3_runtime",
    interpreter_path = "{python_bin}",
    python_version = "PY3",
)

py_runtime_pair(
    name = "nix_py_runtime_pair",
    py3_runtime = ":nix_py3_runtime",
)

toolchain(
    name = "toolchain",
    toolchain = ":nix_py_runtime_pair",
    toolchain_type = "@rules_python//python:toolchain_type",
)
'''.format(python_bin = python_bin))

find_nix_python = repository_rule(
    implementation = _find_nix_python_impl,
    local = True,
    environ = ["PATH"],
)

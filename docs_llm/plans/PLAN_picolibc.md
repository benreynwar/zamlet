# Plan: Switch Kernel Tests from Custom C Runtime to picolibc

## Context

The kernel test programs are compiled with Clang for bare-metal RISC-V and run in a
Python-based VPU simulator. The current C runtime (crt.S, syscalls.c, custom header shims)
is derived from riscv-proxy-kernel. Clang's optimizer is aggressively removing the TLS
initialization code in syscalls.c, causing uninitialized TLS variables (putchar buffer)
and crashes. Rather than patching this fragile setup, we're switching to picolibc -- a
maintained, Clang-compatible embedded C library that handles TLS, BSS, printf, and string
functions correctly.

## What picolibc replaces

| Current file | Replacement |
|---|---|
| `syscalls.c` (printf, memcpy, memset, strlen, exit, TLS init) | picolibc `libc.a` |
| Custom `stdio.h`, `stdlib.h`, `string.h`, `assert.h`, `math.h` | picolibc headers |
| `init_tls()` in syscalls.c | picolibc's crt0 TLS init (in assembly, can't be optimized away) |

## What we keep

- `crt.S` (modified) -- vector/FPU unit init, trap handler, gp/tp/sp setup
- `vpu_alloc.c/h` -- VPU memory pool allocator
- `encoding.h` -- CSR macros
- `util.h` -- test verification helpers
- `test.ld` (modified) -- custom memory layout with VPU regions
- HTIF tohost/fromhost protocol (reimplemented as picolibc `_write`/`_exit` stubs)

## Steps

### 1. Build picolibc as a Nix derivation

Create `nix/picolibc.nix`:
- Fetch picolibc source (pin to a stable release tag)
- Cross-compile with our Clang for `riscv64-unknown-elf`, `rv64gcv`, `lp64d`
- Use meson with a cross-file pointing to our Clang/LLD
- Key meson options: `-Dmultilib=false`, `-Dtls-model=local-exec`,
  `-Dnewlib-global-errno=true`
- Produces a sysroot with `lib/libc.a`, `lib/libm.a`, and `include/` headers

Wire into `nix/common.nix` and export `PICOLIBC_SYSROOT` env var in the shell.

### 2. Create HTIF I/O backend

New file: `common/htif_io.c`
- `_write(fd, buf, count)` -- HTIF syscall (SYS_write=64 via tohost/fromhost)
- `_exit(code)` -- write `(code << 1) | 1` to tohost
- `_read`, `_close`, `_lseek` -- stubs returning -1/0

Move from `syscalls.c` to a new `common/htif_trap.c`:
- `setStats()`, `handle_trap()`, `tohost_exit()` (used by util.h and trap handler)

### 3. Modify crt.S

Keep our `_start` for hardware-specific init (GPR zeroing, FPU/Vector enable via
mstatus, FPU register zeroing, trap handler, gp/tp/sp setup).

Replace the `j _init` with:
- BSS zeroing loop (using `__bss_start`/`__bss_end` symbols)
- TLS init (copy tdata, zero tbss using picolibc-compatible linker symbols)
- Call `main(0, 0)`
- Call `exit()` with return value

We do BSS/TLS in assembly so the compiler can't optimize it away.

### 4. Update linker script (test.ld)

Add sections/symbols picolibc expects:
- `__bss_start` / `__bss_end` around BSS
- TLS symbols: `__tls_base`, `__tdata_source`, `__tdata_size`, `__tbss_size`
- `.init_array` / `.fini_array` sections with start/end symbols
- `.rodata` section (picolibc format strings)

Keep all VPU sections and tohost unchanged.

### 5. Update Bazel build

Modify `riscv_kernel` rule in `bazel/defs.bzl`:
- Remove `-nostdlib`, keep `-nostartfiles` (we provide `_start`)
- Remove `-fno-builtin-printf`
- Add `--sysroot=$PICOLIBC_SYSROOT`
- Add `-lc -lm`
- Pass sysroot via `--action_env=PICOLIBC_SYSROOT` in `.bazelrc`

Update `common/BUILD`:
- Replace `syscalls.c` with `htif_io.c` and `htif_trap.c` in filegroups
- Remove custom header shims from headers filegroup

### 6. Delete replaced files

- Delete `syscalls.c`
- Delete custom `stdio.h`, `stdlib.h`, `string.h`, `assert.h`, `math.h`

## Key files to modify

- `nix/picolibc.nix` (new)
- `nix/common.nix`
- `python/zamlet/kernel_tests/common/crt.S`
- `python/zamlet/kernel_tests/common/test.ld`
- `python/zamlet/kernel_tests/common/htif_io.c` (new)
- `python/zamlet/kernel_tests/common/htif_trap.c` (new)
- `python/zamlet/kernel_tests/common/BUILD`
- `bazel/defs.bzl`

## Verification

1. Build picolibc in Nix, verify `libc.a` exists with expected symbols
2. Compile minimal `int main() { return 0; }` test, inspect ELF for correct layout
3. Run in simulator, verify exit code 0
4. Compile test with `printf("hello\n")`, verify output appears
5. Compile test with `__thread` variable, verify TLS init in disassembly
6. Run full test suite: `bazel test //python/zamlet/kernel_tests/... --test_output=errors`
7. Compare against current baseline

## Risks

- picolibc may not build cleanly with our bleeding-edge Clang (v23). Test early.
- Bazel sandbox may not see the picolibc sysroot. Use `--action_env` and ensure
  Nix store paths are accessible.
- Symbol conflicts between our stubs and picolibc (e.g. `exit`). Use `-nostartfiles`
  and only provide `_write`/`_exit`/`_read`/`_close`/`_lseek`.

# Minimal C runtime for simple VPU test
# No BSS initialization, no TLS, no constructors

  .section ".text.init"
  .globl _start
_start:
  # Set up stack pointer at end of scalar memory (2MB from 0x10000000)
  li sp, 0x10200000

  # Call main
  call main

  # Exit with return code from main (in a0)
  # Write to tohost: (exit_code << 1) | 1
  slli a0, a0, 1
  ori a0, a0, 1
  la t0, tohost
  sd a0, 0(t0)

  # Spin forever
1:
  j 1b

.section ".tohost","aw",@progbits
.align 6
.globl tohost
tohost: .dword 0
.align 6
.globl fromhost
fromhost: .dword 0

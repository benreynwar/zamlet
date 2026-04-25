#include <stdint.h>

#include "encoding.h"
#include "util.h"

#define FAULT_ADDR ((uintptr_t)0x40000000UL)

static volatile uintptr_t trap_count;
static volatile uintptr_t last_cause;
static volatile uintptr_t last_epc;
static volatile uintptr_t last_tval;

uintptr_t handle_trap(uintptr_t cause, uintptr_t epc, uintptr_t regs[32])
{
  (void)regs;
  trap_count++;
  last_cause = cause;
  last_epc = epc;
  last_tval = read_csr(mtval);
  return epc + insn_len(epc);
}

static int check_trap(uintptr_t expected_count, uintptr_t expected_cause)
{
  if (trap_count != expected_count)
    return 10 + expected_count;
  if (last_cause != expected_cause)
    return 20 + expected_count;
  if (last_tval != FAULT_ADDR)
    return 30 + expected_count;
  if (last_epc == 0)
    return 40 + expected_count;
  return 0;
}

int main(int argc, char** argv)
{
  (void)argc;
  (void)argv;

  asm volatile(
      ".option push\n"
      ".option norvc\n"
      "lw x0, 0(%0)\n"
      ".option pop\n"
      :
      : "r"(FAULT_ADDR)
      : "memory");

  int err = check_trap(1, CAUSE_LOAD_PAGE_FAULT);
  if (err)
    return err;

  asm volatile(
      ".option push\n"
      ".option norvc\n"
      "sw x0, 0(%0)\n"
      ".option pop\n"
      :
      : "r"(FAULT_ADDR)
      : "memory");

  err = check_trap(2, CAUSE_STORE_PAGE_FAULT);
  if (err)
    return err;

  return 0;
}

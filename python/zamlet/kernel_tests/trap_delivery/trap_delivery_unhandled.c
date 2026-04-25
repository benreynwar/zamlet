#include <stdint.h>

#define FAULT_ADDR ((uintptr_t)0x40000000UL)

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

  return 0;
}

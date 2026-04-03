/* Minimal freestanding stdio.h for bare-metal RISC-V kernels.
 * Declares functions implemented in syscalls.c.
 */
#ifndef _STDIO_H
#define _STDIO_H

#include <stddef.h>

int printf(const char* fmt, ...);
int sprintf(char* str, const char* fmt, ...);
int putchar(int ch);

#endif

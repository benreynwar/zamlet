/* Minimal freestanding stdlib.h for bare-metal RISC-V kernels.
 * Declares functions implemented in syscalls.c.
 */
#ifndef _STDLIB_H
#define _STDLIB_H

#include <stddef.h>

void exit(int code);
void abort(void);
long atol(const char* str);

#endif

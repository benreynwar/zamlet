/* Minimal freestanding assert.h for bare-metal RISC-V kernels. */
#ifndef _ASSERT_H
#define _ASSERT_H

void exit(int code);

#ifdef NDEBUG
#define assert(expr) ((void)0)
#else
#define assert(expr) ((expr) ? (void)0 : (exit(1)))
#endif

#endif

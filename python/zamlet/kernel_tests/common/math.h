/* Minimal freestanding math.h for bare-metal RISC-V kernels. */
#ifndef _MATH_H
#define _MATH_H

static inline double fabs(double x) {
    double result;
    __asm__ ("fabs.d %0, %1" : "=f"(result) : "f"(x));
    return result;
}

static inline float fabsf(float x) {
    float result;
    __asm__ ("fabs.s %0, %1" : "=f"(result) : "f"(x));
    return result;
}

#endif

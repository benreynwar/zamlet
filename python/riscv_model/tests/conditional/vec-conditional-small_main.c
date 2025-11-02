// See LICENSE for license details.

//**************************************************************************
// Conditional benchmark - small version
//--------------------------------------------------------------------------

#include <string.h>
#include "util.h"
#include "vpu_alloc.h"

//--------------------------------------------------------------------------
// Input/Reference Data

#include "dataset_small.h"
#include <stdio.h>

//--------------------------------------------------------------------------
// Main

static int verify_short(int n, const volatile int16_t* test, const int16_t* verify)
{
  int i;
  for (i = 0; i < n; i++)
  {
    int t = test[i];
    int v = verify[i];
    if (t != v) return i+1;
  }
  return 0;
}

void vec_conditional(size_t n, int8_t x[], int16_t a[], int16_t b[], int16_t z[]);

int main( int argc, char* argv[] )
{
  int16_t* results_data = (int16_t*)vpu_alloc(DATA_SIZE * sizeof(int16_t), 16);

  // Do the conditional
  setStats(1);
  vec_conditional(DATA_SIZE, input1_data, input2_data, input3_data, results_data);
  setStats(0);

  return verify_short(DATA_SIZE, results_data, verify_data );
}

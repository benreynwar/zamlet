// See LICENSE for license details.

//**************************************************************************
// Conditional benchmark - tiny version
//--------------------------------------------------------------------------

#include <string.h>
#include "util.h"
#include "vpu_alloc.h"

//--------------------------------------------------------------------------
// Input/Reference Data

#include "dataset_tiny.h"
#include <stdio.h>

//--------------------------------------------------------------------------
// Main

static int verify_long(int n, const volatile int64_t* test, const int64_t* verify)
{
  int i;
  for (i = 0; i < n; i++)
  {
    int64_t t = test[i];
    int64_t v = verify[i];
    if (t != v) return i+1;
  }
  return 0;
}


void vec_conditional(size_t n, int64_t x[], int64_t a[], int64_t b[], int64_t z[]);

int main( int argc, char* argv[] )
{
  int64_t* results_data = (int64_t*)vpu_alloc(DATA_SIZE * sizeof(int64_t), 64);

  // Do the conditional
  setStats(1);
  vec_conditional(DATA_SIZE, input1_data, input2_data, input3_data, results_data);
  setStats(0);

  return verify_long(DATA_SIZE, results_data, verify_data );
}

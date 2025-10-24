// See LICENSE for license details.

//**************************************************************************
// SGEMV benchmark (large version - exceeds 256 byte cache)
//--------------------------------------------------------------------------
//
// This benchmark tests a vectorized sgemv implementation with larger data.

#include <string.h>
#include <stdio.h>
#include "util.h"
#include "vpu_alloc.h"

//--------------------------------------------------------------------------
// Input/Reference Data

#include "dataset_large.h"

//--------------------------------------------------------------------------
// Main

void *vec_sgemv (size_t, size_t, const float*, const float*, float*);

int main( int argc, char* argv[] )
{
  float* results_data = vpu_alloc(N_DIM * sizeof(float), 32);
  memset(results_data, 0, N_DIM * sizeof(float));

  printf("sgemv M,N = %ld,%ld\n", M_DIM, N_DIM);
#if PREALLOCATE
  // If needed we preallocate everything in the caches
  vec_sgemv(M_DIM, N_DIM, input_data_x, input_data_A, results_data);
  memset(results_data, 0, N_DIM * sizeof(float));
#endif

  // Do the sgemv
  setStats(1);
  vec_sgemv(M_DIM, N_DIM, input_data_x, input_data_A, results_data);
  setStats(0);

  // Check the results
  return verifyFloat( N_DIM, results_data, verify_data );
}

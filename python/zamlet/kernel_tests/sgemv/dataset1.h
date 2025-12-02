#define M_DIM 8
#define N_DIM 8
#define DIM_SIZE 64

float input_data_A[M_DIM * N_DIM] __attribute__((section(".data.vpu32"), aligned(0x400))) = {
  0.0, 0.0, 0.0, 0.0, 1.0, 2.0, 0.0, 1.0,
  2.0, 4.0, 0.0, 2.0, 4.0, 0.0, 0.0, 0.0,
  2.0, 0.0, 1.0, 0.0, 0.0, 4.0, 0.0, 0.0,
  0.0, 1.0, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0,
  0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
  0.0, 4.0, 2.0, 0.0, 2.0, 0.0, 0.0, 0.0,
  0.0, 4.0, 4.0, 4.0, 1.0, 2.0, 4.0, 0.0,
  4.0, 4.0, 2.0, 2.0, 0.0, 2.0, 0.0, 0.0,
};

float input_data_x[M_DIM] __attribute__((section(".data.vpu32"), aligned(0x400))) = {
  0.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
};

float verify_data[N_DIM] __attribute__((section(".data.vpu32"), aligned(0x400))) = {
  4.0, 12.0, 2.0, 4.0, 10.0, 0.0, 0.0, 0.0,
};

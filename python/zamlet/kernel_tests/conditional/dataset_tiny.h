
#define DATA_SIZE 3

int64_t input1_data[DATA_SIZE] __attribute__((section(".data.vpu64"), aligned(VLMAX_BYTES))) =
{
    0,   3,   8
};

int64_t input2_data[DATA_SIZE] __attribute__((section(".data.vpu64"), aligned(VLMAX_BYTES))) =
{
  100, 10, 1 
};

int64_t input3_data[DATA_SIZE] __attribute__((section(".data.vpu64"), aligned(VLMAX_BYTES))) =
{
  200,  20, 2 
};

int64_t verify_data[DATA_SIZE] __attribute__((section(".data.vpu64"), aligned(VLMAX_BYTES))) =
{
  100, 10, 2 
};


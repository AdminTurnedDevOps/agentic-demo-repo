#include <cuda_runtime.h>

#include <cstdio>
#include <cstdlib>
#include <vector>

#define CUDA_CHECK(call)                                                       \
  do {                                                                         \
    cudaError_t status = (call);                                                \
    if (status != cudaSuccess) {                                                \
      std::fprintf(stderr, "%s failed: %s\n", #call,                         \
                   cudaGetErrorString(status));                                 \
      return EXIT_FAILURE;                                                      \
    }                                                                           \
  } while (0)

__global__ void add_vectors(const int *left, const int *right, int *output,
                            int count) {
  int index = blockIdx.x * blockDim.x + threadIdx.x;
  if (index < count) {
    output[index] = left[index] + right[index];
  }
}

int main() {
  constexpr int item_count = 4096;
  constexpr int block_size = 256;
  constexpr size_t byte_count = item_count * sizeof(int);

  int device_count = 0;
  CUDA_CHECK(cudaGetDeviceCount(&device_count));
  if (device_count < 1) {
    std::fprintf(stderr, "no CUDA devices are visible\n");
    return EXIT_FAILURE;
  }

  CUDA_CHECK(cudaSetDevice(0));

  cudaDeviceProp properties{};
  CUDA_CHECK(cudaGetDeviceProperties(&properties, 0));

  std::vector<int> left(item_count, 1);
  std::vector<int> right(item_count, 2);
  std::vector<int> output(item_count, 0);

  int *device_left = nullptr;
  int *device_right = nullptr;
  int *device_output = nullptr;

  CUDA_CHECK(cudaMalloc(&device_left, byte_count));
  CUDA_CHECK(cudaMalloc(&device_right, byte_count));
  CUDA_CHECK(cudaMalloc(&device_output, byte_count));
  CUDA_CHECK(cudaMemcpy(device_left, left.data(), byte_count,
                        cudaMemcpyHostToDevice));
  CUDA_CHECK(cudaMemcpy(device_right, right.data(), byte_count,
                        cudaMemcpyHostToDevice));

  add_vectors<<<(item_count + block_size - 1) / block_size, block_size>>>(
      device_left, device_right, device_output, item_count);
  CUDA_CHECK(cudaGetLastError());
  CUDA_CHECK(cudaDeviceSynchronize());
  CUDA_CHECK(cudaMemcpy(output.data(), device_output, byte_count,
                        cudaMemcpyDeviceToHost));

  for (int value : output) {
    if (value != 3) {
      std::fprintf(stderr, "vector verification failed: got %d, want 3\n",
                   value);
      return EXIT_FAILURE;
    }
  }

  CUDA_CHECK(cudaFree(device_output));
  CUDA_CHECK(cudaFree(device_right));
  CUDA_CHECK(cudaFree(device_left));
  CUDA_CHECK(cudaDeviceReset());

  std::printf(
      "GPU_PROBE_OK device=0 name=%s vector_items=%d expected_sum=3\n",
      properties.name, item_count);
  return EXIT_SUCCESS;
}

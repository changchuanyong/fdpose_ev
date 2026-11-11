#include <cuda_runtime.h>
#include <cstdio>

#if _MSC_VER != 1938 || CUDART_VERSION != 12080
#error Expected MSVC 14.38 and CUDA Toolkit 12.8
#endif

__global__ void increment(int* value) { *value += 1; }

#define CHECK_CUDA(expr) do { \
    cudaError_t status = (expr); \
    if (status != cudaSuccess) { \
        std::fprintf(stderr, "%s: %s\n", #expr, cudaGetErrorString(status)); \
        return 1; \
    } \
} while (0)

int main() {
    int host = 41;
    int* device = nullptr;
    CHECK_CUDA(cudaMalloc(&device, sizeof(host)));
    CHECK_CUDA(cudaMemcpy(device, &host, sizeof(host), cudaMemcpyHostToDevice));
    increment<<<1, 1>>>(device);
    CHECK_CUDA(cudaGetLastError());
    CHECK_CUDA(cudaDeviceSynchronize());
    CHECK_CUDA(cudaMemcpy(&host, device, sizeof(host), cudaMemcpyDeviceToHost));
    CHECK_CUDA(cudaFree(device));
    if (host != 42) return 1;
    std::puts("PASS NVCC 12.8, MSVC 14.38, compiled CUDA kernel execution");
    return 0;
}

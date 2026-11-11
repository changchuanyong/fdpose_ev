#include <Windows.h>
#include <cstdio>

#if !defined(_WIN64) || _MSC_VER != 1938
#error Expected the approved x64 MSVC 14.38 toolchain
#endif

int main() {
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    if (info.dwNumberOfProcessors == 0) return 1;
    std::printf("PASS MSVC %d, Windows SDK headers, kernel32 linking, x64 executable\n", _MSC_VER);
    return 0;
}

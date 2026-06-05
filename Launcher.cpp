// Launcher.cpp (最终版，修复工作目录)
#include <Windows.h>
#include <shellapi.h>
#include <string>
#include <sstream>
#include "getti.h"

int APIENTRY wWinMain(HINSTANCE, HINSTANCE, LPWSTR, int)
{
    int argc;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argc < 2) {
        MessageBoxW(NULL, L"用法: Launcher.exe 目标程序 [参数...]", L"错误", MB_ICONERROR);
        return 1;
    }

    std::wstring targetCmd;
    for (int i = 1; i < argc; ++i) {
        if (i > 1) targetCmd += L" ";
        targetCmd += argv[i];
    }
    LocalFree(argv);

    // 如果不是 TrustedInstaller，提权并重启自身
    if (!IsTrustedInstaller()) {
        GetTrustedInstaller(TRUE, GetCommandLineW());
        return 0;
    }

    // ---------- 关键修复 ----------
    // 获取 Launcher.exe 所在目录，强制设为子进程的工作目录
    WCHAR szCurDir[MAX_PATH];
    GetModuleFileNameW(NULL, szCurDir, MAX_PATH);
    WCHAR* pLastSlash = wcsrchr(szCurDir, L'\\');
    if (pLastSlash) *pLastSlash = L'\0';   // 去掉自身文件名，保留目录

    // 启动目标进程
    HANDLE hToken = NULL;
    OpenProcessToken(GetCurrentProcess(), TOKEN_ALL_ACCESS, &hToken);
    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi = { 0 };

    BOOL success = CreateProcessAsUserW(
        hToken, NULL, &targetCmd[0],
        NULL, NULL, FALSE, CREATE_NEW_CONSOLE,
        NULL, szCurDir,     // <-- 明确指定工作目录
        &si, &pi);

    if (!success) {
        DWORD err = GetLastError();
        std::wstringstream ss;
        ss << L"启动失败！\n命令行: " << targetCmd
           << L"\n工作目录: " << szCurDir
           << L"\n错误码: " << err;
        MessageBoxW(NULL, ss.str().c_str(), L"Launcher 错误", MB_ICONERROR);
    } else {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }

    CloseHandle(hToken);
    return 0;
}
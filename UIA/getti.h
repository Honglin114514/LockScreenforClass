// getti.h (修正版)
#pragma once

#include <Windows.h>

void GetAdmin(LPWSTR szCmdLine = nullptr);
void GetSystem(LPWSTR szCmdLine = nullptr);
void GetTrustedInstaller(BOOL enableUIAccess = FALSE, LPWSTR szCmdLine = nullptr);

bool StartProcessWithToken(HANDLE hToken, LPWSTR lpCommandLine, PPROCESS_INFORMATION ppi = nullptr);

// 新增：让 Launcher.cpp 能够调用
bool IsTrustedInstaller();
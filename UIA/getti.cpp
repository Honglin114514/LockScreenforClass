// getti.cpp (修正版)
#include "getti.h"
#include <sddl.h>
#include <tlhelp32.h>
#include <vector>
#include <string>

// 将原来的 EnablePrivilege 函数改成下面这个版本
static void EnablePrivilege(HANDLE hToken, LPCWSTR lpszPrivilege, BOOL bEnablePrivilege) {
    LUID luid;
    LookupPrivilegeValueW(NULL, lpszPrivilege, &luid);   // 使用 W 版本
    TOKEN_PRIVILEGES tp;
    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = bEnablePrivilege ? SE_PRIVILEGE_ENABLED : 0;
    AdjustTokenPrivileges(hToken, FALSE, &tp, sizeof(TOKEN_PRIVILEGES), NULL, NULL);
}

static void EnableAllPrivileges(HANDLE hToken, BOOL bEnable) {
    std::vector<std::wstring> lpAllPrivilege = {
        L"SeIncreaseQuotaPrivilege",
        L"SeSecurityPrivilege",
        L"SeTakeOwnershipPrivilege",
        L"SeLoadDriverPrivilege",
        L"SeSystemProfilePrivilege",
        L"SeSystemtimePrivilege",
        L"SeProfileSingleProcessPrivilege",
        L"SeIncreaseBasePriorityPrivilege",
        L"SeCreatePagefilePrivilege",
        L"SeBackupPrivilege",
        L"SeRestorePrivilege",
        L"SeShutdownPrivilege",
        L"SeDebugPrivilege",
        L"SeSystemEnvironmentPrivilege",
        L"SeChangeNotifyPrivilege",
        L"SeRemoteShutdownPrivilege",
        L"SeUndockPrivilege",
        L"SeManageVolumePrivilege",
        L"SeImpersonatePrivilege",
        L"SeCreateGlobalPrivilege",
        L"SeIncreaseWorkingSetPrivilege",
        L"SeTimeZonePrivilege",
        L"SeCreateSymbolicLinkPrivilege",
        L"SeDelegateSessionUserImpersonatePrivilege",
        L"SeSyncAgentPrivilege",
        L"SeCreatePermanentPrivilege",
        L"SeTcbPrivilege",
        L"SeCreateTokenPrivilege",
        L"SeAssignPrimaryTokenPrivilege",
        L"SeLockMemoryPrivilege",
        L"SeMachineAccountPrivilege",
        L"SeAuditPrivilege",
        L"SeTrustedCredManAccessPrivilege",
        L"SeRelabelPrivilege",
        L"SeEnableDelegationPrivilege"
    };
    for (const auto& privilege : lpAllPrivilege) {
        EnablePrivilege(hToken, privilege.c_str(), bEnable);
    }
}

static bool IsAdmin() {
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hToken)) {
        return false;
    }
    TOKEN_ELEVATION te{ 0 };
    DWORD tokenInfoSize = 0;
    BOOL isAdmin = GetTokenInformation(hToken, TokenElevation, &te, sizeof(te), &tokenInfoSize) && te.TokenIsElevated;
    CloseHandle(hToken);
    return isAdmin;
}

static bool IsSystem() {
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ALL_ACCESS, &hToken)) {
        return false;
    }
    BOOL isSystem = FALSE;
    DWORD tokenInfoSize = 0;
    PTOKEN_USER pTokenUser = NULL;
    GetTokenInformation(hToken, TokenUser, NULL, 0, &tokenInfoSize);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
        CloseHandle(hToken);
        return FALSE;
    }
    pTokenUser = (PTOKEN_USER)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, tokenInfoSize);
    if (!pTokenUser) {
        CloseHandle(hToken);
        return FALSE;
    }
    if (GetTokenInformation(hToken, TokenUser, pTokenUser, tokenInfoSize, &tokenInfoSize)) {
        LPSTR pStringSid = NULL;
        if (ConvertSidToStringSidA(pTokenUser->User.Sid, &pStringSid)) {
            if (strcmp(pStringSid, "S-1-5-18") == 0)
                isSystem = TRUE;
            LocalFree(pStringSid);
        }
    }
    if (pTokenUser) {
        HeapFree(GetProcessHeap(), 0, pTokenUser);
    }
    if (hToken) {
        CloseHandle(hToken);
    }
    return isSystem;
}

// 去掉了 static，让 Launcher.cpp 可以调用
bool IsTrustedInstaller() {
    HANDLE hToken = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ALL_ACCESS, &hToken)) {
        return false;
    }
    BOOL isTI = FALSE;
    DWORD tokenInfoSize = 0;
    PTOKEN_GROUPS pTokenGroups = NULL;
    GetTokenInformation(hToken, TokenGroups, NULL, 0, &tokenInfoSize);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
        CloseHandle(hToken);
        return FALSE;
    }
    pTokenGroups = (PTOKEN_GROUPS)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, tokenInfoSize);
    if (!pTokenGroups) {
        CloseHandle(hToken);
        return FALSE;
    }
    if (GetTokenInformation(hToken, TokenGroups, pTokenGroups, tokenInfoSize, &tokenInfoSize)) {
        for (DWORD i = 0; i < pTokenGroups->GroupCount; i++) {
            LPSTR pStringSid = NULL;
            if (ConvertSidToStringSidA(pTokenGroups->Groups[i].Sid, &pStringSid)) {
                if (strstr(pStringSid, "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464") != NULL) {
                    isTI = TRUE;
                    LocalFree(pStringSid);
                    break;
                }
                LocalFree(pStringSid);
            }
        }
    }
    if (pTokenGroups) {
        HeapFree(GetProcessHeap(), 0, pTokenGroups);
    }
    if (hToken) {
        CloseHandle(hToken);
    }
    return isTI;
}

static bool GetSystemToken(PHANDLE phToken) {
    HANDLE hSelfToken = NULL;
    OpenProcessToken(GetCurrentProcess(), TOKEN_ALL_ACCESS, &hSelfToken);
    EnableAllPrivileges(hSelfToken, TRUE);
    BOOL bRet = TRUE;
    DWORD dwUserSessionId;
    ProcessIdToSessionId(GetCurrentProcessId(), &dwUserSessionId);
    PROCESSENTRY32W pe32 = { sizeof(PROCESSENTRY32W) };
    HANDLE hSnapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    for (Process32FirstW(hSnapshot, &pe32); Process32NextW(hSnapshot, &pe32);) {
        if (_wcsicmp(pe32.szExeFile, L"winlogon.exe")) {
            continue;
        }
        HANDLE hProcess = OpenProcess(TOKEN_ALL_ACCESS, FALSE, pe32.th32ProcessID);
        HANDLE hToken = NULL;
        OpenProcessToken(hProcess, TOKEN_QUERY | TOKEN_DUPLICATE, &hToken);
        DWORD dwSessionId = 0;
        DWORD dwBufSize = 0;
        if (GetTokenInformation(hToken, TokenSessionId, &dwSessionId, sizeof(dwSessionId), &dwBufSize)) {
            if (dwSessionId != dwUserSessionId) {
                CloseHandle(hToken);
                CloseHandle(hProcess);
                continue;
            }
        }
        else {
            bRet = FALSE;
            CloseHandle(hToken);
            CloseHandle(hProcess);
            continue;
        }
        if (!DuplicateTokenEx(hToken, TOKEN_ALL_ACCESS, NULL, SecurityImpersonation, TokenPrimary, phToken)) {
            bRet = FALSE;
        }
        CloseHandle(hToken);
        CloseHandle(hProcess);
        break;
    }
    CloseHandle(hSnapshot);
    return bRet;
}

static bool GetTrustedInstallerToken(PHANDLE phToken) {
    if (!phToken) return false;
    *phToken = NULL;

    SC_HANDLE hSC = OpenSCManagerW(NULL, NULL, SC_MANAGER_CONNECT);
    if (!hSC) return false;

    SC_HANDLE hSvc = OpenServiceW(hSC, L"TrustedInstaller",
        SERVICE_START | SERVICE_QUERY_STATUS | SERVICE_STOP);
    if (!hSvc) {
        CloseServiceHandle(hSC);
        return false;
    }

    SERVICE_STATUS ss{};
    if (!QueryServiceStatus(hSvc, &ss)) {
        CloseServiceHandle(hSvc);
        CloseServiceHandle(hSC);
        return false;
    }

    if (ss.dwCurrentState != SERVICE_RUNNING) {
        if (ss.dwCurrentState == SERVICE_STOPPED) {
            if (!StartServiceW(hSvc, 0, NULL)) {
                CloseServiceHandle(hSvc);
                CloseServiceHandle(hSC);
                return false;
            }
        }
        for (int i = 0; i < 60; ++i) {
            Sleep(ss.dwWaitHint ? ss.dwWaitHint : 500);
            if (!QueryServiceStatus(hSvc, &ss)) {
                CloseServiceHandle(hSvc);
                CloseServiceHandle(hSC);
                return false;
            }
            if (ss.dwCurrentState == SERVICE_RUNNING) break;
        }
        if (ss.dwCurrentState != SERVICE_RUNNING) {
            CloseServiceHandle(hSvc);
            CloseServiceHandle(hSC);
            return false;
        }
    }

    DWORD pid = 0;
    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnap == INVALID_HANDLE_VALUE) {
        CloseServiceHandle(hSvc);
        CloseServiceHandle(hSC);
        return false;
    }

    PROCESSENTRY32W pe{ sizeof(pe) };
    for (BOOL b = Process32FirstW(hSnap, &pe); b; b = Process32NextW(hSnap, &pe)) {
        if (_wcsicmp(pe.szExeFile, L"TrustedInstaller.exe") == 0) {
            pid = pe.th32ProcessID;
            break;
        }
    }
    CloseHandle(hSnap);
    if (!pid) {
        CloseServiceHandle(hSvc);
        CloseServiceHandle(hSC);
        return false;
    }

    HANDLE hProc = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (!hProc) {
        CloseServiceHandle(hSvc);
        CloseServiceHandle(hSC);
        return false;
    }

    HANDLE hTok = NULL;
    BOOL ok = OpenProcessToken(hProc, TOKEN_QUERY | TOKEN_DUPLICATE, &hTok);
    CloseHandle(hProc);
    if (!ok) {
        CloseServiceHandle(hSvc);
        CloseServiceHandle(hSC);
        return false;
    }

    HANDLE hDup = NULL;
    ok = DuplicateTokenEx(hTok, MAXIMUM_ALLOWED, NULL, SecurityImpersonation, TokenPrimary, &hDup);
    CloseHandle(hTok);
    CloseServiceHandle(hSvc);
    CloseServiceHandle(hSC);
    if (!ok) return false;

    *phToken = hDup;
    return true;
}

static bool EnableUIAccess(PHANDLE phToken) {
    DWORD uiAccess = TRUE;
    if (!SetTokenInformation(*phToken, TokenUIAccess, &uiAccess, sizeof(uiAccess)))
        return false;
    return true;
}

bool StartProcessWithToken(HANDLE hToken, LPWSTR lpCommandLine, PPROCESS_INFORMATION ppi) {
    HANDLE hPrimaryToken = NULL;
    if (!DuplicateTokenEx(hToken, TOKEN_ALL_ACCESS, NULL, SecurityImpersonation, TokenPrimary, &hPrimaryToken)) {
        return false;
    }
    EnableAllPrivileges(hPrimaryToken, TRUE);
    STARTUPINFOW si = { sizeof(STARTUPINFOW) };
    PROCESS_INFORMATION pi = { 0 };
    if (!CreateProcessWithTokenW(hPrimaryToken, LOGON_WITH_PROFILE, NULL, lpCommandLine, CREATE_NEW_CONSOLE, NULL, NULL, &si, &pi)) {
        if (!CreateProcessAsUserW(hPrimaryToken, NULL, lpCommandLine, NULL, NULL, FALSE, CREATE_NEW_CONSOLE, NULL, NULL, &si, &pi)) {
            return false;
        }
        else {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
        }
    }
    else {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    if (ppi) *ppi = pi;
    return true;
}

void GetAdmin(LPWSTR szCmdLine) {
    if (!szCmdLine) {
        WCHAR cmd[MAX_PATH] = { 0 };
        GetModuleFileNameW(NULL, cmd, MAX_PATH);
        szCmdLine = cmd;
    }
    if (IsAdmin()) return;
    SHELLEXECUTEINFOW sei{ sizeof(sei) };
    sei.lpVerb = L"runas";
    WCHAR szPath[MAX_PATH] = { 0 };
    GetModuleFileNameW(NULL, szPath, MAX_PATH);
    sei.lpFile = szPath;
    sei.lpParameters = szCmdLine;
    sei.nShow = SW_SHOWNORMAL;
    ShellExecuteExW(&sei);
    ExitProcess(0);
}

void GetSystem(LPWSTR szCmdLine) {
    if (!szCmdLine) {
        WCHAR cmd[MAX_PATH] = { 0 };
        GetModuleFileNameW(NULL, cmd, MAX_PATH);
        szCmdLine = cmd;
    }
    GetAdmin(szCmdLine);
    if (!IsSystem()) {
        HANDLE hToken = NULL;
        if (GetSystemToken(&hToken)) {
            if (StartProcessWithToken(hToken, szCmdLine)) {
                CloseHandle(hToken);
                ExitProcess(0);
            }
            else {
                CloseHandle(hToken);
                ExitProcess(1);
            }
        }
        else {
            ExitProcess(1);
        }
    }
}

void GetTrustedInstaller(BOOL enableUIAccess, LPWSTR szCmdLine) {
    if (!szCmdLine) {
        WCHAR cmd[MAX_PATH] = { 0 };
        GetModuleFileNameW(NULL, cmd, MAX_PATH);
        szCmdLine = cmd;
    }
    GetSystem(szCmdLine);
    if (!IsTrustedInstaller()) {
        HANDLE hToken = NULL;
        if (GetTrustedInstallerToken(&hToken)) {
            if (enableUIAccess) {
                EnableUIAccess(&hToken);
            }
            if (StartProcessWithToken(hToken, szCmdLine)) {
                CloseHandle(hToken);
                ExitProcess(0);
            }
            else {
                CloseHandle(hToken);
                ExitProcess(1);
            }
        }
        else {
            ExitProcess(1);
        }
    }
}
# hotspot.py
# 只做一件事：执行 netsh wlan start hostednetwork
# 失败只写日志，不抛异常，不影响主程序

import subprocess
import logging


def _run_netsh(args, timeout=10):
    """执行 netsh 命令，安全解码输出。返回 (returncode, output)。"""
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            ["netsh"] + args,
            capture_output=True,
            timeout=timeout,
            creationflags=creationflags,
        )
    except Exception as e:
        return -1, f"执行 netsh 失败: {e}"

    def _decode(b):
        if not b:
            return ""
        for enc in ("gbk", "utf-8", "cp936"):
            try:
                return b.decode(enc)
            except Exception:
                continue
        return b.decode("utf-8", errors="replace")

    out = _decode(result.stdout) + _decode(result.stderr)
    return result.returncode, out.strip()


def start_hostednetwork():
    """启动 Windows 承载网络。返回 (success, message)。"""
    try:
        rc, output = _run_netsh(["wlan", "start", "hostednetwork"])
        logging.info(f"[hotspot] rc={rc} output={output}")

        if rc == 0:
            logging.info("hostednetwork 启动成功")
            return True, output

        # 常见失败：已启动 / 服务未开 / 网卡不支持
        lowered = output.lower()
        if "已启动" in output or "already" in lowered or "has been started" in lowered:
            logging.info("hostednetwork 已经在运行")
            return True, output

        logging.warning(f"hostednetwork 启动失败(rc={rc}): {output}")
        return False, output
    except Exception as e:
        logging.exception("hostednetwork 启动异常")
        return False, str(e)


def query_hostednetwork():
    """查询承载网络状态，返回 (running, output)。"""
    try:
        rc, output = _run_netsh(["wlan", "show", "hostednetwork"])
        running = ("状态" in output and "已启动" in output) or \
                  ("Status" in output and "Started" in output)
        return running, output
    except Exception as e:
        logging.exception("查询 hostednetwork 失败")
        return False, str(e)
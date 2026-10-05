# -*- coding: utf-8 -*-
"""
updater/update.py  —— 外置更新程序
================================================
由主程序以如下方式启动：
    update.exe --pid <主程序PID> --zip <zip路径> --restart <主程序路径>

职责：
    1. 等主程序退出
    2. 校验 zip
    3. 清空 backup/，把程序根目录所有内容移入 backup/（排除 updater/、update/、backup/）
    4. 解压 zip 到程序根目录
    5. 从 backup/ 恢复 lock_config.json、logs/、themes/、plugin/
    6. 启动主程序
    7. 删除 update/，退出

失败时回滚（把 backup/ 内容还原）。
"""

import os
import sys
import time
import shutil
import zipfile
import logging
import argparse
import subprocess

# ---------------- 路径 ----------------
SELF_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
# updater 位于 <root>/updater/ 内，根目录是上一级
if os.path.basename(SELF_DIR).lower() == "updater":
    ROOT_DIR = os.path.dirname(SELF_DIR)
else:
    # 兜底：如果直接放在根目录
    ROOT_DIR = SELF_DIR

BACKUP_DIR = os.path.join(ROOT_DIR, "backup")
UPDATE_DIR = os.path.join(ROOT_DIR, "update")
LOG_DIR = os.path.join(SELF_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "update_log.log")

# 更新时这些目录/文件不动
EXCLUDES = {"updater", "update", "backup"}
# 这些从 backup 恢复覆盖
KEEP_FROM_BACKUP = ["lock_config.json", "logs", "themes", "plugin"]

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
                    format="%(asctime)s - %(levelname)s - %(message)s")


# ---------------- 工具 ----------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True,
                   help="主程序进程 ID，等它退出后再操作")
    p.add_argument("--zip", required=True, help="待解压的 zip 路径")
    p.add_argument("--restart", required=True, help="更新完成后要启动的主程序路径")
    return p.parse_args()


def wait_for_exit(pid, timeout=60):
    try:
        import psutil
        try:
            proc = psutil.Process(pid)
            proc.wait(timeout=timeout)
            logging.info(f"主程序 PID={pid} 已退出")
        except psutil.NoSuchProcess:
            logging.info(f"PID={pid} 不存在，视为已退出")
        except psutil.TimeoutExpired:
            logging.warning(f"等待 PID={pid} 超时，继续")
    except ImportError:
        logging.warning("psutil 不可用，退化为固定等待")
        time.sleep(2)


def verify_zip(path):
    try:
        with zipfile.ZipFile(path, "r") as z:
            bad = z.testzip()
            if bad is not None:
                logging.error(f"zip 内文件损坏：{bad}")
                return False
        return True
    except Exception as e:
        logging.error(f"zip 校验失败：{e}")
        return False


def clear_backup():
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    logging.info(f"已清空并重建 {BACKUP_DIR}")


def move_root_to_backup():
    moved = []
    for name in os.listdir(ROOT_DIR):
        if name.lower() in EXCLUDES:
            continue
        src = os.path.join(ROOT_DIR, name)
        dst = os.path.join(BACKUP_DIR, name)
        shutil.move(src, dst)
        moved.append(name)
    logging.info(f"已移入 backup：{moved}")


def extract_zip_to_root(zip_path):
    """解压 zip 到根目录，跳过 updater/ 目录（正在运行的更新程序无法被覆盖）。"""
    skipped = 0
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.namelist():
            # 归一化分隔符，取顶层目录名
            top = member.replace("\\", "/").split("/", 1)[0].lower()
            if top == "updater":
                logging.debug(f"跳过 updater 内文件：{member}")
                skipped += 1
                continue
            z.extract(member, ROOT_DIR)
    logging.info(f"已解压 {zip_path} → {ROOT_DIR}（跳过 updater 内 {skipped} 项）")


def restore_kept_files():
    for name in KEEP_FROM_BACKUP:
        src = os.path.join(BACKUP_DIR, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(ROOT_DIR, name)
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        logging.info(f"已从 backup 恢复：{name}")


def rollback():
    """把 backup 的内容还原回根目录。"""
    logging.warning("执行回滚…")
    # 清空根目录非排除项
    for name in os.listdir(ROOT_DIR):
        if name.lower() in EXCLUDES:
            continue
        p = os.path.join(ROOT_DIR, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass

    # 从 backup 恢复（关键：确保目标不存在，否则 move 会嵌套）
    for name in os.listdir(BACKUP_DIR):
        src = os.path.join(BACKUP_DIR, name)
        dst = os.path.join(ROOT_DIR, name)
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
            else:
                try:
                    os.remove(dst)
                except OSError:
                    pass
        shutil.move(src, dst)
    logging.warning("回滚完成")


def launch_main(restart_path):
    if not os.path.isabs(restart_path):
        restart_path = os.path.join(ROOT_DIR, restart_path)
    if not os.path.exists(restart_path):
        logging.error(f"启动目标不存在：{restart_path}")
        return False
    try:
        ext = os.path.splitext(restart_path)[1].lower()
        if ext == ".bat":
            # 用 cmd /c start 打开 bat，独立新窗口，工作目录设在程序根目录
            subprocess.Popen(
                ["cmd", "/c", "start", "", restart_path],
                cwd=ROOT_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            os.startfile(restart_path)
        logging.info(f"已启动主程序：{restart_path}")
        return True
    except Exception as e:
        logging.exception(f"启动主程序失败：{e}")
        return False


def remove_update_dir():
    if os.path.exists(UPDATE_DIR):
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
        logging.info(f"已删除 {UPDATE_DIR}")


def show_message(title, msg, flags=0x40):
    """0x40 = 信息图标，0x10 = 错误图标"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, flags)
    except Exception:
        print(f"[{title}] {msg}", file=sys.stderr)


# ---------------- 主流程 ----------------
def main():
    args = parse_args()
    logging.info(f"更新程序启动，参数：pid={args.pid}, zip={args.zip}, restart={args.restart}")

    wait_for_exit(args.pid)

    if not verify_zip(args.zip):
        logging.error("zip 校验失败，中止更新")
        show_message("更新程序", "更新包损坏，更新已取消。", 0x10)
        return 1

    try:
        clear_backup()
        move_root_to_backup()
        extract_zip_to_root(args.zip)
        restore_kept_files()
        logging.info("文件替换完成")

        remove_update_dir()

        if not launch_main(args.restart):
            show_message("更新程序",
                         f"文件已更新，但启动主程序失败。\n请手动运行：\n{args.restart}",
                         0x10)
            return 1

        logging.info("更新流程完成，更新程序退出")
        return 0

    except Exception as e:
        logging.exception("更新过程异常")
        try:
            rollback()
        except Exception as re:
            logging.exception(f"回滚失败：{re}")
            show_message("更新程序",
                         f"更新失败且回滚失败：\n{e}\n{re}",
                         0x10)
            return 1
        show_message("更新程序",
                     f"更新失败，已回滚到旧版本。\n错误：{e}",
                     0x10)
        return 1


if __name__ == "__main__":
    sys.exit(main())
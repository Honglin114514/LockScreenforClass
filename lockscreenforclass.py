import sys
import json
import hashlib
import os
import logging
import string
import subprocess
import requests
import win32com.client
import ctypes
from datetime import datetime, timedelta  
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction,
                             QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QMessageBox, QStyle,
                             QDialog, QGridLayout, QFrame,QGraphicsOpacityEffect,QTextBrowser
                            )
from PyQt5.QtCore import QTimer, Qt, QDateTime, QPropertyAnimation, QEasingCurve, pyqtSignal,QRectF,QSequentialAnimationGroup, QThread
from PyQt5.QtGui import QPixmap, QPainter , QPainterPath,QFont, QFontMetrics, QColor
import urllib.request
import win32api
import win32gui
import win32process
import psutil
import qrcode
import win32con
import win32security
from video import DynamicWallpaper
import queue
import threading
from web_control import WebControlServer
from hotspot import start_hostednetwork


import ctypes, sys
print("IsUserAnAdmin:", ctypes.windll.shell32.IsUserAnAdmin())
print("IsUserAnAdmin(bypass):", ctypes.windll.shell32.IsUserAnAdmin())
# ---------- 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(BASE_DIR, "lock_config.json")
QR_CODE_FILE = os.path.join(BASE_DIR, "unlock_qrcode.png")

# ---------- 日志 ----------
LOG_FILE = os.path.join(LOG_DIR, "Lock_log.log")
logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


# ---------- 配置读写 ----------
# 默认键表：必须覆盖设置界面能写、以及本程序会读的全部键。
# 原来这份表只有 31 个键、内嵌在 load_config() 里，而 save_config() 会把内存里
# 这份配置整个覆盖回文件，于是 check_update_async() 这类"读一次就存"的路径
# 会把缺失的键永久写丢。现在提升为模块级常量并补齐，用 setdefault 只补不清。
DEFAULT_CONFIG = {
    "background": "",
    "periods": [
    ],
    "exam_date": "",
    "clock_color": "#ffffff",
    "countdown_text": "",
    "countdown_enabled": False,
    "shutdown_enabled": True,
    "shutdown_color": "rgba(255,0,0,200)",
    "shutdown_hover_color": "rgba(255,0,0,200)",
    "shutdown_text": "关机",
    "unlock_color": "rgba(0,100,255,200)",
    "whiteboard_color": "rgba(0,200,100,200)",
    "whiteboard_text": "白板",
    "password_bg": "D:/python文件/LAZY-CLS/Lock Screen for Class/11 (2).jpeg",
    "password_opacity": 0.8,
    "whiteboard_enabled": True,
    "unlock_text": "解锁",
    "password": "114514",
    "quit_requires_password": True,
    "usb_key_file": "key.txt",
    "seewo_path": "",
    "whiteboard_max": 3,
    "strong_periods": [
    ],
    "auto_start": 1,
    "settings_require_auth": 0,
    "settings_background": "",
    "exemption_enabled": True,
    "exemption_apps": [
        "EasiNote.exe",
        "EasiCamera.exe"
    ],
    "exemption_wait_time": 3,
    "exemption_check_interval": 2,
    "password_encrypted": False,
    # ---------- 以下键原来缺失，会被 save_config 写丢 ----------
    "no_version": "",
    "auto_update": False,
    "update_date": "",
    "old_version": "",
    "update_mirror": "",
    "download_proxy": "",
    "last_update_check": 0,
    "dynamic_wallpaper_enabled": False,
    "dynamic_wallpaper_path": "",
    "dynamic_wallpaper_muted": True,
    "web_server_enabled": False,
    "web_server_bind": "0.0.0.0",
    "web_server_port": 8765,
    "auto_start_hotspot": False,
    "software_list": [],
    "password_bg_color": "#A6000000",
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            # 只补缺失键，不覆盖用户已有值
            for key, value in DEFAULT_CONFIG.items():
                config.setdefault(key, value)
            return config
        except Exception as e:
            logging.error(f"配置文件解析失败：{e}")
            return dict(DEFAULT_CONFIG)
    else:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        return dict(DEFAULT_CONFIG)


def get_main_program_path():
    """获取主程序自身路径"""
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    exe_path = os.path.join(base_dir, "lockscreenforclass.exe")
    if os.path.exists(exe_path):
        return exe_path
    py_path = os.path.join(base_dir, "lockscreenforclass.pyw")
    if os.path.exists(py_path):
        return py_path
    return None

def get_startup_target_path():
    """获取开机自启的目标路径"""
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    bat_path = os.path.join(base_dir, "start.bat")
    if os.path.exists(bat_path):
        return bat_path
    #  start.bat 不存在，使用主程序本身
    exe_path = os.path.join(base_dir, "lockscreenforclass.exe")
    if os.path.exists(exe_path):
        return exe_path
    py_path = os.path.join(base_dir, "lockscreenforclass.pyw")
    if os.path.exists(py_path):
        return py_path
    return None

def apply_auto_startup(config):
    """根据配置开机自（写入公共启动文件夹）"""
    target = get_startup_target_path()
    if not target:
        logging.error("未找到启动目标")
        return
    startup_folder = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"
    link_path = os.path.join(startup_folder, "LockScreenForClass.lnk")
    
    try:
        if config.get('auto_start', 0) == 1:
            shell = win32com.client.Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(link_path)
            shortcut.TargetPath = target
            shortcut.WorkingDirectory = os.path.dirname(target)
            shortcut.Save()
            logging.info(f"开机自启已添加，目标: {target}")
        else:
            if os.path.exists(link_path):
                os.remove(link_path)
                logging.info("开机自启移除")
    except Exception as e:
        logging.error(f"设置开机自启失败: {e}")
        
def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def request_shutdown(reboot=False):
    """执行关机/重启。用 subprocess 代替 os.system，避免闪出 cmd 黑窗。"""
    args = ["shutdown", "/r" if reboot else "/s", "/t", "0"]
    try:
        subprocess.Popen(
            args,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        logging.error(f"执行{'重启' if reboot else '关机'}失败：{e}")
        return False

# ---------- 二维码 ----------
def generate_unlock_qr():
    config = load_config()
    if config.get("password_encrypted", False):
        logging.info("密码已加密，二维码未生成")
        return
    password = config.get("password", "114514")
    img = qrcode.make(password)
    img.save(QR_CODE_FILE)
    logging.debug("二维码已生成")

def find_usb_key_file(key_filename):
    """扫描所有盘符寻找 U 盘钥匙文件，返回命中的路径或 None。

    某些映射盘/无介质读卡器在访问盘符时会抛 OSError，
    原来直接调 os.path.exists 会让整次扫描中断。
    """
    if not key_filename:
        return None
    for drive in string.ascii_uppercase:
        usb_path = f"{drive}:\\{key_filename}"
        try:
            if os.path.exists(usb_path):
                return usb_path
        except OSError:
            continue
    return None


def get_screen_scale():
    """以1080p高度为基准，返回缩放系数"""
    screen = QApplication.primaryScreen()
    if not screen:
        return 1.0
    height = screen.size().height()
    return height / 1080.0

# ==================== 版本与更新工具 ====================
def normalize_tag(tag):
    tag = (tag or "").strip()
    if tag and tag[0] in "vV":
        tag = tag[1:]
    return tag

def parse_version(tag):
    nums = []
    for p in normalize_tag(tag).split("."):
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    return tuple(nums)

def compare_versions(a, b):
    va, vb = parse_version(a), parse_version(b)
    n = max(len(va), len(vb))
    va = va + (0,) * (n - len(va))
    vb = vb + (0,) * (n - len(vb))
    if va > vb: return 1
    if va < vb: return -1
    return 0

def is_newer(latest, current):
    return compare_versions(latest, current) > 0

def fetch_latest_release(proxies=None):
    """返回 (tag, zip_url, body)；失败返回 (None, None, None)"""
    try:
        r = requests.get(UPDATE_API_URL,
                         headers={"User-Agent": USER_AGENT},
                         proxies=proxies,
                         timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logging.error(f"检查更新失败：{e}")
        return None, None, None

    tag = data.get("tag_name", "")
    if not tag:
        return None, None, None

    zip_url = None
    for asset in data.get("assets", []):
        if asset.get("name", "").lower() == RELEASE_ZIP_NAME.lower():
            zip_url = asset.get("browser_download_url")
            break

    body = data.get("body", "") or ""
    return tag, zip_url, body

def apply_mirror(url, mirror):
    if not mirror:
        return url
    return mirror.rstrip("/") + "/" + url

def build_proxies(proxy_cfg):
    """把配置字符串解析为 requests 的 proxies dict。空返回 None。"""
    if not proxy_cfg or not isinstance(proxy_cfg, str):
        return None
    s = proxy_cfg.strip()
    if not s:
        return None
    # 只写端口 → 补 127.0.0.1
    if "://" not in s and ":" not in s:
        s = f"127.0.0.1:{s}"
    # 缺协议 → 补 http://
    if "://" not in s:
        s = "http://" + s
    return {"http": s, "https": s}

def compute_wait_ms(hhmm):
    """计算距离下一个 HH:MM 的毫秒数；无效返回 None"""
    if not hhmm or not isinstance(hhmm, str):
        return None
    try:
        h, m = hhmm.strip().split(":")
        h, m = int(h), int(m)
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
    except Exception:
        return None
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(0, int((target - now).total_seconds() * 1000))

generate_unlock_qr()

# ---------- 更新相关常量 ----------
CURRENT_VERSION = "v0.7.2"                     # 硬编码，每次发版改这里
GITHUB_REPO     = "Honglin114514/LockScreenforClass"
RELEASE_ZIP_NAME = "lockscreenforclass.zip"      # Release 里 asset 的名字（全小写）
UPDATE_API_URL  = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT      = "LockScreenForClass-Updater/1.0"

UPDATE_DIR = os.path.join(BASE_DIR, "update")
UPDATE_ZIP = os.path.join(UPDATE_DIR, "latest.zip")
UPDATER_DIR = os.path.join(BASE_DIR, "updater")

# ================== 关机红色遮罩 ==================
class ShutdownOverlay(QWidget):
    confirmed = pyqtSignal()
    canceled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: rgba(255, 0, 0, 150);")

        scale = get_screen_scale()
        title_font_size = int(48 * scale)
        subtitle_font_size = int(24 * scale)
        btn_font_size = int(24 * scale)
        btn_padding = int(12 * scale)
        btn_min_width = int(140 * scale)
        btn_border_radius = int(12 * scale)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        layout.setAlignment(Qt.AlignCenter)

        # 标题
        title_label = QLabel("确认关机？")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"""
            color: white;
            font-size: {title_font_size}px;
            background:transparent;
            font-weight: bold;
            padding: {int(20 * scale)}px;
            font-family: "Microsoft YaHei", "微软雅黑", "SimHei", sans-serif;
        """)
        layout.addWidget(title_label)

        # 副标题
        subtitle_label = QLabel("一体机将立即关闭，进度将会丢失。")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(f"""
            color: white;
            background:transparent;
            font-size: {subtitle_font_size}px;
            padding: {int(10 * scale)}px;
            font-family: "Microsoft YaHei", "微软雅黑", "SimHei", sans-serif;
        """)
        layout.addWidget(subtitle_label)

        # 按钮布局
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(int(40 * scale))
        btn_layout.setAlignment(Qt.AlignCenter)

        self.cancel_btn = QPushButton("取消")
        self.confirm_btn = QPushButton("确定关机")

        btn_style = f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 200);
                color: #333;
                font-size: {btn_font_size}px;
                font-weight: bold;
                border: none;
                border-radius: {btn_border_radius}px;
                padding: {btn_padding}px {int(32 * scale)}px;
                min-width: {btn_min_width}px;
                font-family: "Microsoft YaHei", "微软雅黑", "SimHei", sans-serif;
            }}
            QPushButton:hover {{
                background-color: white;
            }}
            QPushButton:pressed {{
                background-color: #ddd;
            }}
        """
        self.cancel_btn.setStyleSheet(btn_style)
        self.confirm_btn.setStyleSheet(btn_style)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.confirm_btn)
        layout.addLayout(btn_layout)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(central_widget)
        self.setLayout(main_layout)

        # 连接按钮
        self.cancel_btn.clicked.connect(self._start_fade_out_and_cancel)
        self.confirm_btn.clicked.connect(self._start_fade_out_and_confirm)

    def _start_fade_out_and_confirm(self):
        self._fade_out_and_close(after_close=lambda: self.confirmed.emit())

    def _start_fade_out_and_cancel(self):
        self._fade_out_and_close(after_close=lambda: self.canceled.emit())

    def _fade_out_and_close(self, after_close):
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(200)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.finished.connect(lambda: self._on_fade_out_finished(after_close))
        self.animation.start()

    def _on_fade_out_finished(self, after_close):
        after_close()
        self.close()

    def show_overlay(self):
        self.showFullScreen()
        self.setWindowOpacity(0.0)
        self.raise_()
        self.activateWindow()
        self.anim_in = QPropertyAnimation(self, b"windowOpacity")
        self.anim_in.setDuration(200)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(1.0)
        self.anim_in.setEasingCurve(QEasingCurve.OutCubic)
        self.anim_in.start()

#=============== 提示弹窗部分=================
# -*- coding: utf-8 -*-
"""
toast.py —— 模块化胶囊提示组件
================================================
白底黑字、随文字长度自动伸缩、随屏幕分辨率等比缩放、
显示在屏幕水平居中偏上位置、自带淡入淡出动画。

调用示例（必须在 QApplication 创建之后）：

    from toast import show_toast

    show_toast("物理密钥解锁成功")             # 默认显示 2000 毫秒
    show_toast("白板使用次数已达上限", 3000)    # 自定义显示时间
"""



def _horizontal_advance(fm, text):
    """兼容不同版本的字体宽度测量"""
    if hasattr(fm, "horizontalAdvance"):
        return fm.horizontalAdvance(text)
    return fm.width(text)


class Toast(QWidget):
    """一条白底黑字胶囊提示。"""

    #: 当前屏幕上仍然存活的提示（用于多条提示纵向自动排列）
    _active = []

    #: 距屏幕顶部的高度比例（"居中偏上"）
    TOP_RATIO = 0.08
    #: 多条提示之间的垂直间距比例
    GAP_RATIO = 0.012
    #: 基准分辨率高度（以此高度为 1.0 缩放基准）
    BASE_HEIGHT = 1080.0
    #: 基准字号（像素，1080p 下的实际字号）
    BASE_FONT_SIZE = 24
    #: 淡入 / 淡出时长（毫秒）
    FADE_IN_MS = 220
    FADE_OUT_MS = 320

    # ------------------------------------------------------------------
    def __init__(self, text, duration=2000):
        super().__init__(None)

        self._text = str(text)
        self._duration = max(0, int(duration))

        geo = QApplication.primaryScreen().geometry()

        # ---------------- 尺寸计算（随分辨率缩放） ----------------
        scale = max(0.75, geo.height() / self.BASE_HEIGHT)

        font_size = max(14, int(round(self.BASE_FONT_SIZE * scale)))
        pad_h = int(round(font_size * 1.40))   # 左右内边距
        pad_v = int(round(font_size * 0.60))   # 上下内边距

        font = QFont("Microsoft YaHei")
        font.setPixelSize(font_size)
        fm = QFontMetrics(font)

        # 文字过长时自动换行，避免提示撑出屏幕
        max_text_width = int(geo.width() * 0.72)
        text_width = _horizontal_advance(fm, self._text)
        word_wrap = False
        if text_width > max_text_width:
            text_width = max_text_width
            word_wrap = True
            rect = fm.boundingRect(
                0, 0, max_text_width, 10 ** 6,
                int(Qt.TextWordWrap | Qt.AlignCenter), self._text
            )
            text_height = rect.height()
        else:
            text_height = fm.height()

        # 胶囊最终尺寸：文字尺寸 + 内边距
        w = text_width + 2 * pad_h
        h = text_height + 2 * pad_v
        radius = h // 2          # 圆角取高度一半 → 胶囊形

        # ---------------- 外观 ----------------
        self._label = QLabel(self._text, self)
        self._label.setFont(font)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(word_wrap)
        self._label.setGeometry(0, 0, w, h)
        self._label.setStyleSheet(
            "QLabel {"
            "  background-color: rgba(255, 255, 255, 245);"
            "  color: #000000;"
            f"  border-radius: {radius}px;"
            "}"
        )
        self.setFixedSize(w, h)

        # ---------------- 窗口属性 ----------------
        flags = (Qt.FramelessWindowHint
                 | Qt.WindowStaysOnTopHint
                 | Qt.Tool
                 | getattr(Qt, "WindowDoesNotAcceptFocus", 0))
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)   # 圆角外透明
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)   # 不抢焦点
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 鼠标穿透
        self.setFocusPolicy(Qt.NoFocus)

        # ---------------- 淡入淡出动画 ----------------
        self._effect = QGraphicsOpacityEffect()
        self._effect.setOpacity(0.0)
        self._label.setGraphicsEffect(self._effect)

        fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        fade_in.setDuration(self.FADE_IN_MS)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)

        fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        fade_out.setDuration(self.FADE_OUT_MS)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.InCubic)
        fade_out.finished.connect(self._on_finished)

        self._sequence = QSequentialAnimationGroup(self)
        self._sequence.addAnimation(fade_in)        # 淡入
        self._sequence.addPause(self._duration)     # 停留
        self._sequence.addAnimation(fade_out)       # 淡出

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self):
        """显示提示并开始动画，返回自身。"""
        Toast._active.append(self)
        Toast._relayout()
        self.show()
        self.raise_()
        self._sequence.start()
        return self

    def dismiss(self):
        """立即关闭（一般无需手动调用）。"""
        self._sequence.stop()
        self._cleanup()

    def _on_finished(self):
        self._cleanup()

    def _cleanup(self):
        if self in Toast._active:
            Toast._active.remove(self)
        self.hide()
        self.deleteLater()
        Toast._relayout()

    # ------------------------------------------------------------------
    # 位置排列
    # ------------------------------------------------------------------
    @classmethod
    def _relayout(cls):
        """所有提示水平居中、自上而下依次排列。"""
        if not cls._active:
            return
        geo = QApplication.primaryScreen().geometry()
        y = geo.y() + int(geo.height() * cls.TOP_RATIO)
        gap = int(geo.height() * cls.GAP_RATIO)

        for toast in list(cls._active):
            x = geo.x() + (geo.width() - toast.width()) // 2
            toast.move(x, y)
            y += toast.height() + gap

    @classmethod
    def dismiss_all(cls):
        """关闭当前所有提示。"""
        for toast in list(cls._active):
            toast.dismiss()
# ==================== 异步更新检查 / 下载 ====================
class UpdateChecker(QThread):
    done = pyqtSignal(object)   # (tag, zip_url, body) 或 None

    def __init__(self, proxies=None):
        super().__init__()
        self.proxies = proxies

    def run(self):
        tag, url, body = fetch_latest_release(self.proxies)
        if tag:
            self.done.emit((tag, url, body))
        else:
            self.done.emit(None)

class UpdateDownloader(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, url, dest, proxies=None):
        super().__init__()
        self.url = url
        self.dest = dest
        self.proxies = proxies

    def run(self):
        try:
            os.makedirs(os.path.dirname(self.dest), exist_ok=True)
            logging.info(f"开始下载：{self.url} -> {self.dest}")
            logging.info(f"代理设置：{self.proxies}")   # ← 这行必须有

            with requests.get(self.url, stream=True,
                              proxies=self.proxies,
                              headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                with open(self.dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
            self.done.emit(True, "")
        except Exception as e:
            import traceback
            logging.error(f"下载更新失败：{e}\n{traceback.format_exc()}")
            self.done.emit(False, str(e))


# ----------------------------------------------------------------------
def show_toast(text, duration=2000):
    """显示一条胶囊提示（模块对外唯一入口）。

    :param text:     提示文字
    :param duration: 停留时间（毫秒），默认 2000
    :return:         Toast 实例（可用 .dismiss() 提前关闭）
    """
    if QApplication.instance() is None:
        raise RuntimeError("show_toast() 必须在 QApplication 创建之后调用")
    return Toast(text, duration).start()

# ==================== 锁屏窗口 ====================
class LockScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        screen = QApplication.primaryScreen()
        self.screen_width = screen.size().width()
        self.screen_height = screen.size().height()

        base = 1080
        scale = self.screen_height / base
        self.time_font_size = int(100 * scale)
        self.date_font_size = int(32 * scale)
        self.cd_font_size = int(32 * scale)
        btn_diameter = int(80 * scale)
        btn_font_size = int(22 * scale)

        self.config = load_config()
        clock_color = self.config.get("clock_color", "#FFFFFF")

        # 当前屏上的临时提示（toast）引用。
        # 原来只把 toast 交给 deleteLater，父窗口销毁后可能永远不会回收；
        # check_usb_key 每秒触发一次提示时会持续泄漏控件。
        self._toasts = []

        # 密码框引用 + U 盘解锁挂起标记：
        # 两者用于让"U 盘"与"密码"两条解锁路径并行且只触发一次。
        self._password_dialog = None
        self._usb_unlock_pending = False

        # 背景
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)
        self.load_background()

        # 时间
        self.time_label = QLabel(self)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet(
            f"color:{clock_color}; font-size:{self.time_font_size}px; "
            f"font-weight:bold; font-family:'Microsoft YaHei'; background:transparent;"
        )

        # 日期+星期
        self.date_label = QLabel(self)
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setStyleSheet(
            f"color:{clock_color}; font-size:{self.date_font_size}px; "
            f"font-family:'Microsoft YaHei'; background:transparent;"
        )

        # 倒计时
        self.countdown_label = QLabel(self)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setStyleSheet(
            f"color:{clock_color}; font-size:{self.cd_font_size}px; "
            f"font-family:'Microsoft YaHei'; background:transparent;"
        )

        # 圆形按钮样式
        def circle_btn_style(color, hover_color):
            return f"""
                QPushButton {{
                    background: {color};
                    color: white;
                    font-family: "Microsoft YaHei";
                    font-size: {btn_font_size}px;
                    font-weight: bold;
                    border: none;
                    border-radius: {btn_diameter//2}px;
                    
                    text-align: center;
                }}
                QPushButton:hover {{
                    background: {hover_color};
                }}
            """

        # 读取解锁按钮配置
        unlock_color = self.config.get("unlock_color", "rgba(52,152,219,200)")
        unlock_text = self.config.get("unlock_text", "解锁")

        # 生成按钮样式
        def unlock_btn_style(color):
            return f"""
                QPushButton {{
                    background: {color};
                    color: white;
                    font-family: "Microsoft YaHei";
                    font-size: {btn_font_size}px;
                    font-weight: bold;
                    border: none;
                    border-radius: {btn_diameter//2}px;
                    
                }}
            """

        self.unlock_btn = QPushButton(unlock_text, self)
        self.unlock_btn.setFixedSize(btn_diameter, btn_diameter)
        self.unlock_btn.setStyleSheet(unlock_btn_style(unlock_color))
        self.unlock_btn.clicked.connect(self.unlock_with_password)

        # ---------- 白板 ----------
        wb_color = self.config.get("whiteboard_color", "rgba(46,204,113,200)")
        wb_text = self.config.get("whiteboard_text", "白板")
        wb_enabled = self.config.get("whiteboard_enabled", True)

        def wb_btn_style(color):
            return f"""
                QPushButton {{
                    background: {color};
                    color: white;
                    font-family: "Microsoft YaHei";
                    font-size: {btn_font_size}px;
                    font-weight: bold;
                    border: none;
                    border-radius: {btn_diameter//2}px;
                    
                }}
            """

        self.wb_btn = QPushButton(wb_text, self)
        self.wb_btn.setFixedSize(btn_diameter, btn_diameter)
        self.wb_btn.setStyleSheet(wb_btn_style(wb_color))
        self.wb_btn.clicked.connect(self.unlock_and_launch)
        print(wb_enabled)
        if not wb_enabled:
            self.wb_btn.hide()

        # ---------- 关机 ----------
        shutdown_enabled = self.config.get("shutdown_enabled", True)
        shutdown_color = self.config.get("shutdown_color", "rgba(231,76,60,200)")
        shutdown_hover_color = self.config.get("shutdown_hover_color", "rgba(231,76,60,240)")
        shutdown_text = self.config.get("shutdown_text", "关机")

        self.shutdown_btn = QPushButton(shutdown_text, self)
        self.shutdown_btn.setFixedSize(btn_diameter, btn_diameter)
        self.shutdown_btn.setStyleSheet(circle_btn_style(shutdown_color, shutdown_hover_color))
        self.shutdown_btn.clicked.connect(self.confirm_shutdown)
        if not shutdown_enabled:
            self.shutdown_btn.hide()

        # 布局
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)

        # 顶部留白
        vbox.addStretch(1)

        # 上半区：时间、日期、倒计时
        top_area = QVBoxLayout()
        top_area.setSpacing(int(10 * scale))
        top_area.addWidget(self.time_label, alignment=Qt.AlignCenter)
        top_area.addWidget(self.date_label, alignment=Qt.AlignCenter)
        top_area.addSpacing(int(5 * scale))
        top_area.addWidget(self.countdown_label, alignment=Qt.AlignCenter)
        vbox.addLayout(top_area)

        # 时间区与按钮区之间的间隔
        vbox.addStretch(2.5)

        ## 按钮区：固定宽度容器，居中
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(int(20 * scale))

        # 添加三个按钮
        btn_layout.addWidget(self.unlock_btn)
        btn_layout.addWidget(self.wb_btn)
        btn_layout.addWidget(self.shutdown_btn)

        # 将按钮容器添加到垂直布局并居中
        vbox.addWidget(btn_container, alignment=Qt.AlignCenter)

        # 按钮下方留白
        vbox.addStretch(1)

        self.setLayout(vbox)

        # 定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_datetime)
        self.timer.start(1000)
        self.update_datetime()

        self.usb_timer = QTimer(self)
        self.usb_timer.timeout.connect(self.check_usb_key)
        self.usb_timer.start(1000)

        self.setWindowOpacity(0.0)   # 初始完全透明，等待动画显示

        self.showFullScreen()
        # 三按钮自动隐藏机制
        self.buttons_visible = False
        self.hide_btn_timer = QTimer(self)
        self.hide_btn_timer.setSingleShot(True)
        self.hide_btn_timer.timeout.connect(self.hide_buttons)

        # 初始隐藏按钮
        self.unlock_btn.hide()
        self.wb_btn.hide()
        self.shutdown_btn.hide()

        # 启用鼠标追踪
        self.setMouseTracking(True)
        self.raise_()
        self.updata_background_for_strong_period()

    def load_background(self):
        # 动态壁纸模式：背景留空，让下面的视频窗口露出来
        if self.main_app.wallpaper is not None:
            self.bg_label.setPixmap(QPixmap())
            self.bg_label.setStyleSheet("background-color: transparent;")
            return

        bg_path = self.config.get("background", "")
        if bg_path and os.path.exists(bg_path):
            self.bg_label.setPixmap(QPixmap(bg_path))
        else:
            self.bg_label.setPixmap(QPixmap())
            self.bg_label.setStyleSheet("background-color: transparent;")

    def paintEvent(self, event):
        """
        画一层 alpha=1 的隐形遮罩：
        - 人眼完全看不出（1/255 不透明度）
        - 但 Windows 会认为该像素"有内容"，因此拦截鼠标点击，
          不会像 alpha=0 那样穿透到桌面
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def update_datetime(self):
        now = QDateTime.currentDateTime()
        self.time_label.setText(now.toString("HH:mm:ss"))
        weekdays = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
        wd = weekdays[now.date().dayOfWeek() - 1]
        self.date_label.setText(f"{now.toString('yyyy年M月d日')} {wd}")
        self.update_countdown()

    def update_countdown(self):
        config = load_config()  # 每次读取最新配置
        if not config.get("countdown_enabled", True):
            self.countdown_label.setText("")
            return

        exam_str = config.get("exam_date", "")
        text = config.get("countdown_text", "中考")
        today = datetime.now().date()
        try:
            if exam_str:
                exam_date = datetime.strptime(exam_str, "%Y-%m-%d").date()
                delta = (exam_date - today).days
                if delta > 0:
                    self.countdown_label.setText(f"距{text}还有 {delta} 天")
                elif delta == 0:
                    self.countdown_label.setText(f"开始{text}")
                else:
                    self.countdown_label.setText(f"{text}已结束")
            else:
                self.countdown_label.setText(f"{text}日期未设置")
        except Exception as e:
            logging.error(f"日期解析失败：{e}")
            self.countdown_label.setText(f"{text}日期格式错误")

    def resizeEvent(self, event):
        if hasattr(self, 'bg_label'):
            self.bg_label.setGeometry(0, 0, self.width(), self.height())

    def check_usb_key(self):
        # 只有锁屏窗口真的显示着才处理。
        # 否则解锁之后插入 U 盘也会弹"物理密钥解锁成功"——屏幕根本没锁，提示是假的。
        if not self.isVisible():
            return
        # 单次点火：usb_timer 与密码框路径可能同时命中，只处理第一次
        if self._usb_unlock_pending:
            return
        config = load_config()
        key_filename = config.get("usb_key_file", "unlock.key")
        if not find_usb_key_file(key_filename):
            return

        self._usb_unlock_pending = True
        self.usb_timer.stop()
        self.main_app.set_unlocked_for_period(True)
        show_toast("物理密钥解锁成功")

        if self._password_dialog is not None:
            # 密码框正开着：关掉它（用 reject，不冒充"密码正确"）
            logging.info("密码框显示期间检测到U盘钥匙，执行完整解锁")
            self._password_dialog.reject()
        else:
            logging.info("检测到U盘钥匙，执行完整解锁")

        # 延后到当前事件循环之后：避免在 dialog.exec_() 尚未退栈时
        # 就淡出／销毁锁屏窗口，导致密码框卡在屏幕上
        QTimer.singleShot(0, self.unlock)

    def unlock_with_password(self):
        self.show_buttons_and_reset_timer()
        dialog = PasswordDialog(self)
        self._password_dialog = dialog

        # U 盘钥匙在密码框弹出期间依然有效：
        # 由 LockScreen 每 1 秒触发的 usb_timer -> check_usb_key() 负责检测，
        # 命中后会 reject() 掉这个对话框，这里只负责收尾。
        dialog.finished.connect(self._on_password_dialog_finished)

        accepted = dialog.exec_()

        # 收尾统一走 finished 回调，避免和 U 盘路径重复解锁
        QTimer.singleShot(0, dialog.deleteLater)

    def _on_password_dialog_finished(self, result):
        self._password_dialog = None

        if result == QDialog.Accepted:
            logging.info("密码正确，执行完整解锁")
            self.main_app.set_unlocked_for_period(True)
            self.unlock()
            return

        # 对话框以其他方式关闭（取消／ESC／U盘）
        if not getattr(self, "_usb_unlock_pending", False):
            return
        # 时段结束等外部原因已经把锁屏关掉时，不要再解锁
        if self.main_app.lock_screen is not None and not self.isVisible():
            return
        self.unlock()

    def unlock_and_launch(self):
        self.show_buttons_and_reset_timer()
        logging.info("白板按钮被点击")

        if self.main_app.exemption_wait_timer.isActive():
            self.show_toast("正在检测中，请稍候...")
            return

        if not self.main_app.try_whiteboard_click():
            self.show_toast("白板使用次数已达上限")
            return

        config = load_config()
        path = config.get("seewo_path", "")
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                logging.error(f"启动失败: {e}")
                self.wb_btn.setEnabled(True)
                self.show_toast("启动失败，请检查路径配置")
                return
        else:
            self.wb_btn.setEnabled(True)
            self.show_toast("目标程序路径无效")
            return

        # 始终启动等待检测
        self.main_app.start_exemption_wait()
        self.show_toast(f"请等待启动，超时秒数： {self.main_app.exemption_wait_time} ")

    def confirm_shutdown(self):
        self.show_buttons_and_reset_timer()
        self.overlay = ShutdownOverlay()
        self.overlay.confirmed.connect(self._do_shutdown)
        self.overlay.canceled.connect(self._on_shutdown_cancel)
        self.overlay.show_overlay()

    def _do_shutdown(self):
        logging.info("用户确认关机")
        request_shutdown(reboot=False)
        # 遮罩会自行关闭并淡出

    def _on_shutdown_cancel(self):
        logging.info("用户取消关机")
        # 无需额外操作，遮罩已关闭

    def show_toast(self, message, duration=2000):
        screen = QApplication.primaryScreen()
        screen_width = screen.size().width()
        screen_height = screen.size().height()
        scale = screen_height / 1080
        font_size = max(12, min(32, int(16 * scale)))
        padding_v = int(font_size * 0.5)
        padding_h = int(font_size * 1.2)
        border_radius = int(font_size * 0.3)

        toast = QLabel(message, self)
        toast.setAlignment(Qt.AlignCenter)
        toast.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 180);
                color: white;
                font-size: {font_size}px;
                font-family: "Microsoft YaHei";
                border-radius: {border_radius}px;
                padding: {padding_v}px {padding_h}px;
            }}
        """)
        toast.adjustSize()
        x = (screen_width - toast.width()) // 2
        y = screen_height // 12
        toast.move(x, y)
        toast.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        toast.show()

        self._toasts.append(toast)

        def _cleanup(t=toast):
            if t in self._toasts:
                self._toasts.remove(t)
            try:
                t.hide()
                t.setParent(None)
                t.deleteLater()
            except RuntimeError:
                pass  # 底层 C++ 对象已随父窗口销毁

        QTimer.singleShot(duration, _cleanup)

    def unlock(self):
        logging.info("解锁，开始淡出")
        self.usb_timer.stop()
        self.timer.stop()
        self.unlock_btn.setEnabled(False)
        self.wb_btn.setEnabled(False)
        self.main_app.stop_wallpaper()
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.setEasingCurve(QEasingCurve.InCubic)
        self.animation.finished.connect(self._after_fade_out)
        self.animation.start()

    def _after_fade_out(self):
        self.main_app.on_lock_screen_closed(self)
        self.close()

    def keyPressEvent(self, event):
        pass

    def closeEvent(self, event):
        event.accept()

    def mousePressEvent(self, event):
        # 屏幕上任意位置点击，显示按钮并重置计时器
        self.show_buttons_and_reset_timer()
        # 不要忽略事件，让按钮也能收到点击信号
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 移动不需要处理，忽略即可（性能考虑）
        event.ignore()

    def mouseReleaseEvent(self, event):
        # 同样转发
        super().mouseReleaseEvent(event)

    def show_buttons_and_reset_timer(self):
        self.config = load_config()  # 每次显示前读取最新配置
        if not self.buttons_visible:
            # 解锁按钮始终显示
            self.unlock_btn.show()
            # 白板按钮根据配置显示
            if self.config.get("whiteboard_enabled", True):
                self.wb_btn.show()
            # 关机按钮根据配置显示
            if self.config.get("shutdown_enabled", True):
                self.shutdown_btn.show()
            self.buttons_visible = True
        # 重启5秒倒计时（无论之前是否可见）
        self.hide_btn_timer.stop()
        self.hide_btn_timer.start(5000)

    def hide_buttons(self):
        self.unlock_btn.hide()
        self.wb_btn.hide()
        self.shutdown_btn.hide()
        self.buttons_visible = False

    def updata_background_for_strong_period(self):
        in_strong = self.main_app.is_in_strong_period()

        if in_strong:
            # 铺纯黑，盖住视频
            self.bg_label.setStyleSheet("background-color: black;")
            self.bg_label.setPixmap(QPixmap())
            # 视频如果还在跑，停一次（is_running 保证只停一次）
            if self.main_app.wallpaper and self.main_app.wallpaper.is_running():
                self.main_app.wallpaper.stop()
        else:
            # 退出强时段 或 本来就非强时段
            if self.main_app.wallpaper:
                # 视频没在跑就恢复（只恢复一次）
                if not self.main_app.wallpaper.is_running():
                    self.main_app.wallpaper.start()
            else:
                self.load_background()

    # ==================== 密码对话框 ====================
class PasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.password = ""

        # 先读取配置
        config = load_config()
        bg_path = config.get("password_bg", "")
        bg_color_str = config.get("password_bg_color", "#A6000000")
        self.bg_color = QColor(bg_color_str)   # 直接可用
        opacity = config.get("password_opacity", 1.0)
        self.target_opacity = opacity

        # 获取屏幕并计算所有尺寸参数（先于任何UI创建）
        screen = QApplication.primaryScreen()
        screen_height = screen.size().height()
        base_height = 1080
        scale = screen_height / base_height
        self.scale = scale

        self.dialog_width = int(400 * scale)
        self.dialog_height = int(520 * scale)
        self.title_font_size = int(24 * scale)
        self.dots_font_size = int(32 * scale)
        self.button_font_size = int(18 * scale)
        self.button_min_width = int(70 * scale)
        self.button_min_height = int(55 * scale)
        self.border_radius = int(20 * scale)   # 现在 border_radius 已定义
        self.btn_border_radius = int(10 * scale)
        self.spacing = int(20 * scale)
        self.margin = int(40 * scale)
        self.grid_spacing = int(12 * scale)

        #圆形键盘按钮
        self.num_btn_size   = int(56 * scale)     # 直径（正方形边长）
        self.num_btn_radius = self.num_btn_size // 2

        #确认/取消的胶囊尺寸
        self.pill_height    = int(38 * scale)
        self.pill_radius    = self.pill_height // 2
        self.pill_font_size = int(15 * scale)

        # 背景图片（保存原始 pixmap）
        self.bg_pixmap = None
        if bg_path and os.path.exists(bg_path):
            self.bg_pixmap = QPixmap(bg_path)

        # 创建UI
        self.init_ui()
        self.setStyleSheet(self.get_stylesheet())

        # 设置固定大小
        right_width = int(self.dialog_width * 0.5)
        total_width = self.dialog_width + right_width + 20
        self.setFixedSize(total_width, self.dialog_height)

        # 确保背景图片被绘制（不需要额外标签）
            
    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.border_radius, self.border_radius)
        painter.setClipPath(path)

        # ① 半透明底色：永远先铺（这就是"看不清"的解药）
        painter.fillRect(rect, self.bg_color)

        # ② 有图就叠上去；没有就只留底色
        if self.bg_pixmap and not self.bg_pixmap.isNull():
            scaled = self.bg_pixmap.scaled(
                rect.width(), rect.height(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

    def get_stylesheet(self):
        return f"""
            QDialog {{ background: transparent; border-radius: {self.border_radius}px; }}
            QLabel {{ color: #333333; font-family: "Microsoft YaHei"; }}

            /* 通用：只负责外观，不设 min/max，交给 setFixedSize */
            QPushButton {{
                background-color: #f0f0f0;
                color: #333333;
                border: none;
                border-radius: {self.btn_border_radius}px;
                font-family: "Microsoft YaHei";
                font-size: {self.button_font_size}px;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton:hover   {{ background-color: #00aaff; color: white; }}
            QPushButton:pressed {{ background-color: #0088cc; }}

            /* 数字键：正方形 + 半径=半边长 = 圆 */
            QPushButton#numBtn {{
                background-color: #f0f0f0;
                color: #333333;
                border: none;
                border-radius: {self.num_btn_radius}px;
                min-width: {self.num_btn_size}px;
                max-width: {self.num_btn_size}px;
                min-height: {self.num_btn_size}px;
                max-height: {self.num_btn_size}px;
                font-family: "Microsoft YaHei";
                font-size: {self.button_font_size}px;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton#numBtn:hover   {{ background-color: #00aaff; color: white; }}
            QPushButton#numBtn:pressed {{ background-color: #0088cc; }}

            /* 回退 / 清空：同样是圆，字号缩一点塞得进 */
            QPushButton#funcBtn {{
                background-color: #f0f0f0;
                color: #333333;
                border: none;
                border-radius: {self.num_btn_radius}px;
                min-width: {self.num_btn_size}px;
                max-width: {self.num_btn_size}px;
                min-height: {self.num_btn_size}px;
                max-height: {self.num_btn_size}px;
                font-family: "Microsoft YaHei";
                font-size: {int(self.button_font_size * 0.72)}px;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton#funcBtn:hover   {{ background-color: #00aaff; color: white; }}
            QPushButton#funcBtn:pressed {{ background-color: #0088cc; }}

            /* 确认 / 取消：白底胶囊、小一号、宽度按内容走 */
            QPushButton#confirmBtn, QPushButton#cancelBtn {{
                background-color: #ffffff;
                color: #333333;
                border: none;
                border-radius: {self.pill_radius}px;
                font-family: "Microsoft YaHei";
                font-size: {self.pill_font_size}px;
                font-weight: bold;
                padding: 0 {int(24 * self.scale)}px;
            }}
            QPushButton#confirmBtn:hover   {{ background-color: #e8f5ee; color: #00aa66; }}
            QPushButton#confirmBtn:pressed {{ background-color: #d0ebdd; }}
            QPushButton#cancelBtn:hover    {{ background-color: #fdeaea; color: #cc3333; }}
            QPushButton#cancelBtn:pressed  {{ background-color: #f8d5d5; }}
        """

    def init_ui(self):
            main_layout = QHBoxLayout()
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(10)

            left_container = QFrame(self)
            left_container.setObjectName("leftContainer")
            left_container.setStyleSheet(f"""
                QFrame#leftContainer {{
                    background-color: transparent;
                    border: none;
                    border-radius: {self.border_radius}px;
                }}
            """)
            left_layout = QVBoxLayout(left_container)
            left_layout.setSpacing(self.spacing)
            left_layout.setContentsMargins(self.margin, self.margin, self.margin, self.margin)

            title = QLabel("请输入密码")
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet(f"font-size: {self.title_font_size}px; font-weight: bold; color: white;")
            left_layout.addWidget(title)

            self.dots_label = QLabel()
            self.dots_label.setAlignment(Qt.AlignCenter)
            self.dots_label.setStyleSheet(f"color: #00aaff; font-size: {self.dots_font_size}px; font-family: monospace; letter-spacing: {int(self.dots_font_size * 0.4)}px;")
            self.dots_label.setFixedHeight(int(self.dots_font_size * 1.8))
            left_layout.addWidget(self.dots_label)
            self.update_dots()

            grid = QGridLayout()
            grid.setSpacing(self.grid_spacing)
            buttons = [
                ('1', 0, 0), ('2', 0, 1), ('3', 0, 2),
                ('4', 1, 0), ('5', 1, 1), ('6', 1, 2),
                ('7', 2, 0), ('8', 2, 1), ('9', 2, 2),
                ('<', 3, 0), ('0', 3, 1), ('X', 3, 2),
            ]
            for text, row, col in buttons:
                btn = QPushButton(text)
                btn.clicked.connect(self.on_button_clicked)
                # 数字键 → 圆形；回退/清空 → 圆形但字号缩小
                btn.setFixedSize(self.num_btn_size, self.num_btn_size)
                if text in ('<', 'X'):
                    btn.setObjectName("funcBtn")
                else:
                    btn.setObjectName("numBtn")
                grid.addWidget(btn, row, col)
            left_layout.addLayout(grid)

            btn_layout = QHBoxLayout()
            btn_layout.setSpacing(self.spacing)

            # 按数字矩阵的实际宽度，让两个胶囊平分这一行
            grid_width = 3 * self.num_btn_size + 2 * self.grid_spacing
            pill_width = (grid_width - self.spacing) // 1.6   # 减去两个胶囊之间的间距
            confirm_btn = QPushButton("确 认")
            confirm_btn.setObjectName("confirmBtn")
            confirm_btn.setFixedSize(pill_width, self.pill_height)
            cancel_btn = QPushButton("取 消")
            cancel_btn.setObjectName("cancelBtn")
            cancel_btn.setFixedSize(pill_width, self.pill_height)
            confirm_btn.clicked.connect(self.check_password)
            cancel_btn.clicked.connect(self.animate_reject)
            btn_layout.addWidget(confirm_btn)
            btn_layout.addWidget(cancel_btn)
            left_layout.addLayout(btn_layout)

            # 右侧容器（二维码或提示）
            right_container = QFrame(self)
            right_container.setFixedWidth(int(self.dialog_width * 0.5))
            right_container.setObjectName("rightContainer")
            right_container.setStyleSheet(f"""
                QFrame#rightContainer {{
                    background-color: transparent;
                    border: none;
                    border-radius: {self.border_radius}px;
                }}
            """)
            right_layout = QVBoxLayout(right_container)
            right_layout.setAlignment(Qt.AlignCenter)
            right_layout.setContentsMargins(self.margin//2, self.margin, self.margin//2, self.margin)

            # 读取加密配置
            config = load_config()
            password_encrypted = config.get("password_encrypted", False)

            if not password_encrypted:
                # 明文模式：显示二维码
                qr_label = QLabel()
                if os.path.exists(QR_CODE_FILE):
                    qr_pixmap = QPixmap(QR_CODE_FILE)
                    qr_width = int(self.dialog_width * 0.4)
                    qr_pixmap = qr_pixmap.scaledToWidth(qr_width, Qt.SmoothTransformation)
                    qr_label.setPixmap(qr_pixmap)
                    qr_label.setToolTip("请扫码获取密码")
                else:
                    qr_label.setText("二维码文件缺失")
                    qr_label.setStyleSheet("color: red; font-size: 14px;")
                right_layout.addWidget(qr_label)

                tip_text = "扫码获取密码"
            else:
                # 加密模式：显示提示
                tip_label_enc = QLabel("哈希加密中")
                tip_label_enc.setAlignment(Qt.AlignCenter)
                tip_label_enc.setStyleSheet(f"font-size: {self.title_font_size}px; color: #FFFFFF; font-weight: bold;")
                right_layout.addWidget(tip_label_enc)
                tip_text = "密码已加密，扫码无效"

            # 下方提示标签
            tip_label = QLabel(tip_text)
            tip_label.setAlignment(Qt.AlignCenter)
            tip_label.setStyleSheet(f"font-size: {int(self.title_font_size * 0.6)}px; color: white; margin-top: 10px;")
            right_layout.addWidget(tip_label)

            

            main_layout.addWidget(left_container)
            main_layout.addWidget(right_container)

            outer_layout = QVBoxLayout()
            outer_layout.setContentsMargins(0, 0, 0, 0)
            outer_layout.addLayout(main_layout)
            self.setLayout(outer_layout)

    def on_button_clicked(self):
            btn = self.sender()
            text = btn.text()
            if text == '<':
                self.password = self.password[:-1]
            elif text == 'X':
                self.password = ""
            else:
                self.password += text
            self.update_dots()
            self.dots_label.setStyleSheet(f"color: #00aaff; font-size: {self.dots_font_size}px; font-family: monospace; letter-spacing: {int(self.dots_font_size * 0.4)}px;")

    def update_dots(self):
            self.dots_label.setText("●" * len(self.password))

    def show_error_flash(self):
            original_style = self.dots_label.styleSheet()
            self.dots_label.setStyleSheet(f"color: #ff3333; font-size: {self.dots_font_size}px; font-family: monospace; letter-spacing: {int(self.dots_font_size * 0.4)}px;")
            QTimer.singleShot(500, lambda: self.reset_after_error(original_style))

    def reset_after_error(self, original_style):
            self.dots_label.setStyleSheet(original_style)
            self.password = ""
            self.update_dots()

    def check_password(self):
        config = load_config()
        correct = config.get("password", "114514")
        if config.get("password_encrypted", False):
            # 启用加密：对输入计算 SHA-256 哈希后比较
            input_hash = hashlib.sha256(self.password.encode('utf-8')).hexdigest()
            if input_hash == correct:
                self.accept()
            else:
                self.show_error_flash()
        else:
            # 明文比较
            if self.password == correct:
                self.accept()
            else:
                self.show_error_flash()

    def animate_reject(self):
            self.anim = QPropertyAnimation(self, b"windowOpacity")
            self.anim.setDuration(200)
            self.anim.setStartValue(1.0)
            self.anim.setEndValue(0.0)
            self.anim.finished.connect(self.reject)
            self.anim.start()

    def showEvent(self, event):
        self.setWindowOpacity(0)
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(200)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1.0)   
        self.anim.start()
        super().showEvent(event)

# ==================== 更新提示窗口 ====================
class UpdateDialog(QDialog):
    """发现新版本提示窗；白底黑字，展示 release notes，锁屏风格缩放 + 淡入淡出。"""
    def __init__(self, current_version, latest_version, release_body="", parent=None):
        super().__init__(parent)
        self.action = None   # 'update' / 'cancel' / 'ignore'

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        scale = max(0.75, geo.height() / 1080.0)

        # 尺寸：比之前更高，给 release notes 留位置
        w = int(640 * scale)
        h = int(560 * scale)
        r = int(20 * scale)
        pad = int(28 * scale)
        title_size = int(28 * scale)
        info_size = int(18 * scale)
        body_size = int(15 * scale)
        btn_size = int(18 * scale)
        btn_h = int(48 * scale)

        self.setFixedSize(w, h)

        card = QFrame(self)
        card.setObjectName("updateCard")
        card.setGeometry(0, 0, w, h)
        card.setStyleSheet(f"""
            QFrame#updateCard {{
                background-color: #ffffff;
                border-radius: {r}px;
            }}
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(int(12 * scale))

        # 标题
        title = QLabel("发现新版本")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f'color: #1a1a1a; font-family: "Microsoft YaHei"; '
            f'font-size: {title_size}px; font-weight: bold; '
            f'background: transparent;')
        layout.addWidget(title)

        # 版本信息
        info = QLabel(f"{current_version}  →  {latest_version}")
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet(
            f'color: #666666; font-family: "Microsoft YaHei"; '
            f'font-size: {info_size}px; background: transparent;')
        layout.addWidget(info)

        # 更新内容标题
        section = QLabel("更新内容")
        section.setStyleSheet(
            f'color: #333333; font-family: "Microsoft YaHei"; '
            f'font-size: {int(body_size * 1.15)}px; font-weight: bold; '
            f'background: transparent;')
        layout.addWidget(section)

        # release notes 滚动区（关键：QTextBrowser + setMarkdown）
        self.body_view = QTextBrowser()
        self.body_view.setOpenExternalLinks(True)   # 链接可点
        self.body_view.setFrameShape(QFrame.NoFrame)
        self.body_view.setStyleSheet(f"""
            QTextBrowser {{
                background-color: #f7f7f9;
                color: #222222;
                border: 1px solid #e0e0e0;
                border-radius: {int(8 * scale)}px;
                padding: {int(10 * scale)}px;
                font-family: "Microsoft YaHei";
                font-size: {body_size}px;
            }}
        """)
        # Qt 5.14+ 直接支持 Markdown
        text = release_body.strip() or "（此版本未提供更新说明）"
        try:
            self.body_view.setMarkdown(text)
        except AttributeError:
            # 老版本 Qt 兜底：纯文本显示
            self.body_view.setPlainText(text)
        layout.addWidget(self.body_view, 1)   # 拉伸因子 1，占满剩余空间

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(int(15 * scale))

        def _mk_btn(text, bg, hover, fg="#ffffff"):
            b = QPushButton(text)
            b.setStyleSheet(f"""
                QPushButton {{
                    color: {fg};
                    font-family: "Microsoft YaHei";
                    font-size: {btn_size}px;
                    font-weight: bold;
                    border: none;
                    border-radius: {btn_h // 2}px;
                    min-height: {btn_h}px;
                    padding: 0 {int(18 * scale)}px;
                    background-color: {bg};
                }}
                QPushButton:hover {{ background-color: {hover}; }}
            """)
            return b

        ignore_btn = _mk_btn("忽略此版本",   "#f0d0d0", "#e0b0b0", fg="#993333")
        cancel_btn = _mk_btn("取消",         "#e0e0e0", "#d0d0d0", fg="#333333")
        update_btn = _mk_btn("更新",         "#00aa66", "#00cc77")

        ignore_btn.clicked.connect(lambda: self._act("ignore"))
        cancel_btn.clicked.connect(lambda: self._act("cancel"))
        update_btn.clicked.connect(lambda: self._act("update"))
        
        btn_layout.addWidget(ignore_btn)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(update_btn)
        layout.addLayout(btn_layout)

        x = geo.x() + (geo.width() - w) // 2
        y = geo.y() + (geo.height() - h) // 2
        self.move(x, y)

    # _act / _fade_out_and_close / showEvent 与之前完全一样，不用改

    def _act(self, action):
        self.action = action
        self._fade_out_and_close()

    def _fade_out_and_close(self):
        self._anim_out = QPropertyAnimation(self, b"windowOpacity")
        self._anim_out.setDuration(200)
        self._anim_out.setStartValue(self.windowOpacity())
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.InCubic)
        self._anim_out.finished.connect(self.accept)
        self._anim_out.start()

    def showEvent(self, event):
        self.setWindowOpacity(0.0)
        self._anim_in = QPropertyAnimation(self, b"windowOpacity")
        self._anim_in.setDuration(200)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_in.start()
        super().showEvent(event)

# ==================== 主控程序 ====================
class MainApp:
    def __init__(self):
        logging.info("初始化完成，主程序启动")
        def excepthook(exc_type, exc_value, exc_tb):
            logging.critical("未捕获的异常", exc_info=(exc_type, exc_value, exc_tb))
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        sys.excepthook = excepthook

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.lock_screen = None
        self.wallpaper = None 
        self.unlocked_in_period = False
        self.current_period_end = None

        config = load_config()
        apply_auto_startup(config)

        # 白板计数
        self.whiteboard_click_count = 0
        self.whiteboard_max_clicks = config.get("whiteboard_max", 3)
        self.current_period_key = None

        # 不完整解锁监控（仅保留）
        self.incomplete_unlock = False
        self.incomplete_monitor = QTimer()
        self.incomplete_monitor.timeout.connect(self.check_incomplete_fullscreen)

        # 豁免机制相关
        self.exemption_enabled = config.get("exemption_enabled", False)
        self.exemption_wait_time = config.get("exemption_wait_time", 5)
        self.exemption_check_interval = config.get("exemption_check_interval", 2)
        self.exemption_active = False
        self.exemption_running = False
        self.exemption_wait_timer = QTimer()
        self.exemption_wait_timer.setSingleShot(True)
        self.exemption_wait_timer.timeout.connect(self.on_exemption_wait_timeout)
        self.exemption_monitor_timer = QTimer()
        self.exemption_monitor_timer.timeout.connect(self.check_exemption_status)

        # 时间段检测
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_time)
        self.check_timer.start(10000)

        # 外部更新触发轮询
        self.update_trigger_timer = QTimer()
        self.update_trigger_timer.timeout.connect(self.check_update_trigger)
        self.update_trigger_timer.start(3000)   # 3 秒一次

        # ---------- Web 控制 ----------
        self.web_command_queue = queue.Queue()
        self.web_server = None

        # 启动承载网络（后台线程，失败不影响主程序）
        if config.get("auto_start_hotspot", False):
            try:
                threading.Thread(
                    target=start_hostednetwork, daemon=True).start()
            except Exception:
                logging.exception("启动 hotspot 线程失败")

        # 启动 Web 服务（失败不影响主程序）
        if config.get("web_server_enabled", False):
            try:
                self.web_server = WebControlServer(
                    self.web_command_queue,
                    CONFIG_FILE,
                    bind=config.get("web_server_bind", "0.0.0.0"),
                    port=int(config.get("web_server_port", 8765)),
                )
                self.web_server.start()
            except Exception:
                logging.exception("启动 Web 服务失败")
                self.web_server = None

        # 主线程轮询 Web 命令
        self.web_command_timer = QTimer()
        self.web_command_timer.timeout.connect(self.process_web_commands)
        self.web_command_timer.start(100)

        self.setup_tray()

        # 更新相关状态
        self._update_checker = None
        self._downloader = None
        self._pending_tag = None
        self._pending_wait_ms = 0

        self.check_pending_update_result()                     # 启动结果提示
        QTimer.singleShot(2000, self.check_update_async)       # 2 秒后再查更新
        self.check_time()

    def setup_tray(self):
        self.tray = QSystemTrayIcon()
        icon = self.app.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.tray.setToolTip("Lock Screen for Class")

        menu = QMenu()
        lock_action = QAction("立即锁定", menu)
        lock_action.triggered.connect(self.force_lock)
        about_action = QAction("设置", menu)
        about_action.triggered.connect(self.show_about)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.protected_quit)

        menu.addAction(lock_action)
        menu.addAction(about_action)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)

        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()
        logging.debug("系统托盘已显示")

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            logging.info("托盘图标左键点击，立即锁定")
            self.force_lock()

    def force_lock(self):
        logging.info("手动强制锁定")
        self.unlocked_in_period = False
        if self.lock_screen is None:
            self.show_lock_screen()

    def set_unlocked_for_period(self, unlocked):
        self.unlocked_in_period = unlocked
        if unlocked:
            # 手动解锁时，停止所有豁免监控
            if self.exemption_monitor_timer.isActive():
                self.exemption_monitor_timer.stop()
            self.exemption_running = False
            self.exemption_active = False
            if self.exemption_wait_timer.isActive():
                self.exemption_wait_timer.stop()
        logging.debug(f"设置 unlocked_in_period = {unlocked}")

    def should_show_lock(self):
        if not self.is_in_lock_period():
            return False
        if self.unlocked_in_period:
            return False
        # 只有豁免启用且检测到豁免软件全屏时，才阻止锁屏
        if self.exemption_enabled and self.exemption_running:
            return False
        return True

    def update_lock_screen(self):
        should_show = self.should_show_lock()
        if should_show and self.lock_screen is None:
            self.show_lock_screen()
        elif not should_show and self.lock_screen is not None:
            self.hide_lock_screen()

    def check_time(self):
        # 普通时段逻辑
        in_period = self.is_in_lock_period()
        if not hasattr(self, '_last_in_period'):
            self._last_in_period = False
        if in_period and not self._last_in_period:
            logging.info("进入锁定时段，重置完整解锁标志")
            self.unlocked_in_period = False
        self._last_in_period = in_period

        period_key = self.get_period_key()
        if period_key != self.current_period_key:
            self.current_period_key = period_key
            self.whiteboard_click_count = 0
            if self.lock_screen:
                self.lock_screen.wb_btn.setEnabled(True)

        if self.lock_screen is not None:
            self.lock_screen.updata_background_for_strong_period()

        # 管理自动豁免监控
        if self.exemption_enabled:
            if self.is_in_lock_period():
                if not self.exemption_monitor_timer.isActive():
                    self.start_auto_exemption_monitor()
                    # 立即检测一次，确保状态及时更新
                    self.check_exemption_status()
            else:
                if self.exemption_monitor_timer.isActive():
                    self.stop_auto_exemption_monitor()
                self.exemption_running = False
                self.exemption_active = False
        else:
            if self.exemption_monitor_timer.isActive():
                self.exemption_monitor_timer.stop()
            self.exemption_running = False
            self.exemption_active = False

        self.update_lock_screen()

    def get_period_key(self):
        if self.is_in_lock_period():
            return str(self.current_period_end)
        return "none"

    def is_in_lock_period(self):
        config = load_config()
        now = datetime.now().time()
        periods = config.get("periods", [])
        for period in periods:
            start = datetime.strptime(period["start"], "%H:%M").time()
            end = datetime.strptime(period["end"], "%H:%M").time()
            if start <= end:
                if start <= now <= end:
                    self.current_period_end = end
                    return True
            else:
                if now >= start or now <= end:
                    self.current_period_end = end
                    return True
        self.current_period_end = None
        return False

    def is_process_fullscreen(self, process_names):
        """检测指定进程名列表中的任意一个是否在全屏运行（覆盖屏幕98%以上）"""
        def enum_callback(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                hwnds.append(hwnd)
            return True

        hwnds = []
        win32gui.EnumWindows(enum_callback, hwnds)
        screen_width = win32api.GetSystemMetrics(0)
        screen_height = win32api.GetSystemMetrics(1)

        for hwnd in hwnds:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                if proc_name in process_names:
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top, right, bottom = rect
                    width = right - left
                    height = bottom - top
                    if width >= screen_width * 0.98 and height >= screen_height * 0.98:
                        return True
            except:
                continue
        return False

    def get_exemption_apps(self):
        """实时从配置文件读取豁免软件名单"""
        config = load_config()
        return config.get("exemption_apps", ["EasiNote.exe"])

    def is_seewo_running(self):
        return self.is_process_fullscreen(self.get_exemption_apps())

    def try_whiteboard_click(self):
        if self.whiteboard_click_count >= self.whiteboard_max_clicks:
            return False
        self.whiteboard_click_count += 1
        if self.whiteboard_click_count >= self.whiteboard_max_clicks and self.lock_screen:
            self.lock_screen.wb_btn.setEnabled(False)
        return True

    def start_incomplete_monitoring(self):
        # 此方法已弃用，但保留以防外部调用（无实际功能）
        pass

    def check_incomplete_fullscreen(self):
        # 此方法已弃用，保留但无操作
        pass

    # ---------- 豁免相关方法 ----------
    def start_exemption_wait(self):
        """点击白板后启动超时等待检测"""
        if self.exemption_wait_timer.isActive():
            return  # 正在等待，忽略
        self.exemption_wait_timer.start(self.exemption_wait_time * 1000)
        self.exemption_monitor_timer.start(self.exemption_check_interval * 1000)
        self.exemption_active = False
        self.exemption_running = False
        logging.info("开始白板豁免等待检测")

    def on_exemption_wait_timeout(self):
        self.exemption_monitor_timer.stop()
        self.exemption_active = False
        self.exemption_running = False
        if self.lock_screen:
            self.lock_screen.show_toast("白板启动超时，请重试")
            # 仅在本时段还有剩余次数时重新启用白板按钮。
            # 原来无条件 setEnabled(True)，等于同一时段内次数上限失效。
            if self.whiteboard_click_count < self.whiteboard_max_clicks:
                self.lock_screen.wb_btn.setEnabled(True)
        logging.warning("白板启动超时")

    def check_exemption_status(self):
        """周期性检测豁免软件是否全屏运行（点击白板触发或自动监控）"""
        if not self.exemption_enabled:
            # 豁免被关闭：立刻停监控并清状态。
            # 原来只判断"豁免关闭 且 等待计时器未激活"才返回，于是关掉豁免后，
            # 只要仍在点击白板后的等待窗口内，检测照常运行，一旦全屏就会被
            # 误判为豁免成功并解锁。
            if self.exemption_monitor_timer.isActive():
                self.exemption_monitor_timer.stop()
            self.exemption_running = False
            self.exemption_active = False
            return

        running = self.is_process_fullscreen(self.get_exemption_apps())

        if running and not self.exemption_running:
            self.set_unlocked_for_period(True)
            self.exemption_running = True
            self.exemption_active = True
            if self.exemption_wait_timer.isActive():
                self.exemption_wait_timer.stop()
            if self.lock_screen:
                self.lock_screen.unlock()
            logging.info("检测到豁免软件全屏，已解锁并持续监控")
        elif not running and self.exemption_running:
            self.exemption_running = False
            self.exemption_active = False
            self.set_unlocked_for_period(False)
            self.force_lock()
            logging.info("豁免软件退出全屏，已锁定")

    def start_auto_exemption_monitor(self):
        """在锁定时段内启动自动豁免监控（由 check_time 调用）"""
        if self.exemption_enabled and not self.exemption_monitor_timer.isActive():
            self.exemption_monitor_timer.start(self.exemption_check_interval * 1000)
            logging.debug("启动自动豁免监控")

    def stop_auto_exemption_monitor(self):
        """停止自动豁免监控"""
        if self.exemption_monitor_timer.isActive():
            self.exemption_monitor_timer.stop()
        logging.debug("停止自动豁免监控")

    # ---------- 其他已有方法 ----------
    def get_explorer_token(self):
        """获取当前登录用户的 explorer.exe 进程的主令牌"""
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() == 'explorer.exe':
                pid = proc.info['pid']
                h_process = None
                try:
                    # 打开进程
                    h_process = win32api.OpenProcess(
                        win32con.PROCESS_QUERY_INFORMATION,
                        False,
                        pid
                    )
                    # 打开进程令牌（需要复制和赋值权限）
                    h_token = win32security.OpenProcessToken(
                        h_process,
                        win32con.TOKEN_DUPLICATE |
                        win32con.TOKEN_ASSIGN_PRIMARY |
                        win32con.TOKEN_QUERY
                    )
                    return h_token
                except Exception as e:
                    logging.error(f"获取 Explorer 令牌失败 (PID={pid}): {e}")
                    continue
                finally:
                    # 无论成功失败都要关掉进程句柄，否则每次失败泄漏一个句柄
                    if h_process:
                        try:
                            win32api.CloseHandle(h_process)
                        except Exception:
                            pass
        logging.error("未找到可用的 Explorer 进程")
        return None

    def launch_via_explorer_token(self, exe_path, cmdline=""):
        """使用 Explorer 的令牌启动 EXE，彻底剥离 UIAccess 权限"""
        token = self.get_explorer_token()
        if not token:
            logging.error("无法获取 Explorer 令牌，启动失败")
            return False

        hProcess = hThread = None
        try:
            full_cmd = f'"{exe_path}" {cmdline}' if cmdline else exe_path
            startup_info = win32process.STARTUPINFO()
            # 创建标志：使用交互式窗口站，让新进程显示GUI
            creation_flags = win32con.CREATE_NEW_CONSOLE

            # 调用 CreateProcessAsUser
            hProcess, hThread, dwPid, dwTid = win32process.CreateProcessAsUser(
                token,          # 用户令牌
                None,           # 应用程序名（为None时从命令行解析）
                full_cmd,       # 命令行
                None,           # 进程安全属性
                None,           # 线程安全属性
                False,          # 句柄是否可继承
                creation_flags, # 创建标志
                None,           # 环境变量（继承）
                None,           # 工作目录（继承）
                startup_info    # 启动信息
            )
            logging.info(f"通过 Explorer 令牌成功启动 {exe_path} (PID={dwPid})")
            return True
        except Exception as e:
            logging.error(f"CreateProcessAsUser 调用失败: {e}")
            return False
        finally:
            # token / hProcess / hThread 都必须关闭，否则每开一次"设置"泄漏句柄
            try:
                if hProcess:
                    win32api.CloseHandle(hProcess)
            except Exception:
                pass
            try:
                if hThread:
                    win32api.CloseHandle(hThread)
            except Exception:
                pass
            try:
                if token:
                    win32api.CloseHandle(token)
            except Exception:
                pass
    
    def show_lock_screen(self):
        if self.lock_screen is None:
            config = load_config()

            # ① 先起视频（如果有）
            if config.get("dynamic_wallpaper_enabled", False):
                if self.wallpaper is None:
                    self.wallpaper = DynamicWallpaper(
                        config.get("dynamic_wallpaper_path", ""),
                        muted=config.get("dynamic_wallpaper_muted", True))
                if not self.is_in_strong_period():
                    self.wallpaper.start()
            elif self.wallpaper is not None:
                # 配置里已关闭动态壁纸：释放旧实例，
                # 否则它会被一直持有，锁屏还会去 stop/start 它
                try:
                    self.wallpaper.release()
                except Exception:
                    logging.exception("释放动态壁纸失败")
                self.wallpaper = None

            self.lock_screen = LockScreen(main_app=self)
            self.lock_screen.show()
            self.lock_screen.raise_()
            self.lock_screen.activateWindow()
            self.fade_in = QPropertyAnimation(self.lock_screen, b"windowOpacity")
            self.fade_in.setDuration(300)
            self.fade_in.setStartValue(0.0)
            self.fade_in.setEndValue(1.0)
            self.fade_in.setEasingCurve(QEasingCurve.OutCubic)
            self.fade_in.start()
            self.lock_screen.fade_anim = self.fade_in
            logging.debug("锁屏窗口已显示")

    def hide_lock_screen(self):
        # ① 先关视频
        self.stop_wallpaper()

        if self.lock_screen:
            self.fade_out = QPropertyAnimation(self.lock_screen, b"windowOpacity")
            self.fade_out.setDuration(300)
            self.fade_out.setStartValue(1.0)
            self.fade_out.setEndValue(0.0)
            self.fade_out.setEasingCurve(QEasingCurve.InCubic)
            self.fade_out.finished.connect(self._finish_hide_lock_screen)
            self.lock_screen.hide_anim = self.fade_out
            self.fade_out.start()

    def _finish_hide_lock_screen(self):
        if self.lock_screen:
            self.lock_screen.close()
            self.lock_screen = None
        logging.debug("锁屏窗口已隐藏")

    def on_lock_screen_closed(self, lock_screen_instance):
        if self.lock_screen is lock_screen_instance:
            self.lock_screen = None
        logging.debug("锁屏窗口已关闭")

    # ---------- 更新流程 ----------
    def check_pending_update_result(self):
        """上次退出前若写过 old_version，则本次启动时用胶囊提示更新结果。"""
        config = load_config()
        old = config.get("old_version", "")
        if not old:
            return
        # 立刻写空，避免下次再弹
        config["old_version"] = ""
        save_config(config)

        if old != CURRENT_VERSION:
            msg = f"更新成功：{old} → {CURRENT_VERSION}"
        else:
            msg = "更新失败"
        logging.info(f"更新结果提示：{msg}")
        QTimer.singleShot(1000, lambda: show_toast(msg, 3000))

    def _on_update_check_done(self, result):
        if not result:
            return
        tag, zip_url, body = result
        logging.info(f"GitHub 最新版本：{tag}，本机：{CURRENT_VERSION}")

        if not is_newer(tag, CURRENT_VERSION):
            return

        config = load_config()
        if tag == config.get("no_version", ""):
            return

        if config.get("auto_update", False):
            wait_ms = compute_wait_ms(config.get("update_date", ""))
            if wait_ms is None:
                return
            self._start_update_download(zip_url, tag, wait_ms, config)
        else:
            dlg = UpdateDialog(CURRENT_VERSION, tag, body)
            dlg.exec_()
            if dlg.action == "update":
                self._start_update_download(zip_url, tag, 0, config)
            elif dlg.action == "ignore":
                config["no_version"] = tag
                save_config(config)
                logging.info(f"已忽略版本 {tag}")

    def _start_update_download(self, zip_url, latest_tag, wait_ms, config):
        if not zip_url:
            show_toast("未找到下载链接", 3000)
            logging.error("Release 中未找到 zip asset")
            return

        final_url = apply_mirror(zip_url, config.get("update_mirror", ""))
        proxies = build_proxies(config.get("download_proxy", ""))
        logging.info(f"下载 URL: {final_url}，代理: {proxies}")

        show_toast("正在下载更新…", 3000)

        self._pending_tag = latest_tag
        self._pending_wait_ms = wait_ms
        self._downloader = UpdateDownloader(final_url, UPDATE_ZIP, proxies)
        self._downloader.done.connect(self._on_download_done)
        self._downloader.start()

    def _on_download_done(self, success, msg):
        if not success:
            show_toast("更新下载失败", 3000)
            logging.error(f"下载失败：{msg}")
            return
        logging.info(f"下载完成：{UPDATE_ZIP}")

        if self._pending_wait_ms > 0:
            QTimer.singleShot(self._pending_wait_ms, self._launch_updater)
        else:
            QTimer.singleShot(500, self._launch_updater)

    def _launch_updater(self):
        """写 old_version → 启动 updater → 退出主程序。"""
        logging.info("准备启动更新程序")

        # 写 old_version（此刻起可认为更新流程正式启动）
        config = load_config()
        config["old_version"] = CURRENT_VERSION
        save_config(config)

        updater_exe = os.path.join(UPDATER_DIR, "update.exe")
        updater_py  = os.path.join(UPDATER_DIR, "update.py")

        if os.path.exists(updater_exe):
            cmd = [updater_exe]
            cwd = UPDATER_DIR
        elif os.path.exists(updater_py):
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
            cmd = [pythonw, updater_py]
            cwd = UPDATER_DIR
        else:
            show_toast("未找到更新程序", 3000)
            logging.error("updater 不存在")
            return

        restart = get_startup_target_path()
        if not restart:
            show_toast("未找到主程序路径", 3000)
            return

        cmd += ["--pid", str(os.getpid()),
                "--zip", UPDATE_ZIP,
                "--restart", restart]
        logging.info(f"启动更新程序：{cmd}")

        try:
            subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            logging.exception(f"启动更新程序失败：{e}")
            show_toast("启动更新程序失败", 3000)
            return

        self.quit()

    def check_update_trigger(self):
        """轮询 update/trigger.flag，收到就触发一次完整检查。"""
        trigger = os.path.join(UPDATE_DIR, "trigger.flag")
        if not os.path.exists(trigger):
            return
        try:
            os.remove(trigger)
        except Exception:
            pass
        logging.info("收到外部更新触发信号")
        self.check_update_async(force=True)

    def check_update_async(self, force=False):
        config = load_config()
        # 缓存：非强制触发时，1 小时内不重复请求
        if not force:
            last = config.get("last_update_check", 0)
            now = int(datetime.now().timestamp())
            if now - last < 3600:
                logging.debug(f"距上次检查不足 1 小时，跳过")
                return
        config["last_update_check"] = int(datetime.now().timestamp())
        save_config(config)

        proxies = build_proxies(config.get("download_proxy", ""))
        logging.debug(f"检查更新，代理：{proxies}")
        self._update_checker = UpdateChecker(proxies)
        self._update_checker.done.connect(self._on_update_check_done)
        self._update_checker.start()

#----------------------
    def show_about(self):
        # 运行同目录下的 setting.exe
        #subprocess.Popen(['setting.exe'])
        # 获取 setting.exe 的绝对路径
        exe_path = os.path.join(BASE_DIR, "setting.exe")
        if os.path.exists(exe_path):
            success = self.launch_via_explorer_token(exe_path)
            if not success:
                logging.error("启动设置程序失败")
        else:
            logging.error("未找到 setting.exe 文件")

    def check_usb_key_immediate(self):
        config = load_config()
        key = config.get("usb_key_file", "unlock.key")
        return find_usb_key_file(key) is not None

    def protected_quit(self):
        config = load_config()
        if not config.get("quit_requires_password", True):
            self.quit()
            return
        # U 盘钥匙与密码是平级的两种方式：先查 U 盘，没有再给密码机会。
        # 原来写成 if 密码 / elif U盘，导致必须先输错一次密码才会去查 U 盘。
        if self.check_usb_key_immediate():
            logging.info("检测到U盘钥匙，允许退出")
            self.quit()
            return
        dlg = PasswordDialog(self.lock_screen)
        if dlg.exec_() == QDialog.Accepted:
            self.quit()

    def quit(self):
        logging.info("-------退出---------")
        self.exemption_wait_timer.stop()
        self.exemption_monitor_timer.stop()
        if self.wallpaper:
            self.wallpaper.release() 
        if self.lock_screen:
            self.lock_screen.close()
        try:
            if self.web_server:
                self.web_server.stop()
        except Exception:
            logging.exception("停止 Web 服务失败")
        self.app.quit()

    def run(self):
        self.app.exec_()

    def is_in_strong_period(self):
        config = load_config()
        now = datetime.now().time()
        periods = config.get("strong_periods", [])
        for period in periods:
            start = datetime.strptime(period["start"], "%H:%M").time()
            end = datetime.strptime(period["end"], "%H:%M").time()
            if start <= end:
                if start <= now <= end:
                    return True
            else:
                if now >= start or now <= end:
                    return True
        return False

#-------视频相关------------
    def stop_wallpaper(self):
        if self.wallpaper:
            self.wallpaper.stop()

#--------远程相关--------
#  Web 命令处理 
    def process_web_commands(self):
        while True:
            try:
                cmd, params, result_q = self.web_command_queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                logging.exception("读取 Web 命令失败")
                break
            try:
                if cmd == "unlock":
                    self.remote_unlock()
                    result_q.put({"success": True, "message": "已解锁"})
                elif cmd == "lock":
                    self.remote_lock()
                    result_q.put({"success": True, "message": "已锁定"})
                elif cmd == "shutdown":
                    logging.info("远程关机")
                    request_shutdown(reboot=False)
                    result_q.put({"success": True, "message": "正在关机"})
                elif cmd == "reboot":
                    logging.info("远程重启")
                    request_shutdown(reboot=True)
                    result_q.put({"success": True, "message": "正在重启"})
                elif cmd == "toast":
                    msg = params.get("msg", "远程广播")
                    show_toast(msg, 3000)
                    result_q.put({"success": True, "message": f"已广播：{msg}"})
                elif cmd == "status":
                    result_q.put({
                        "success": True,
                        "locked": self.lock_screen is not None,
                    })
                else:
                    result_q.put({"success": False, "message": "未知命令"})
            except Exception as e:
                logging.exception("处理 Web 命令失败")
                try:
                    result_q.put({"success": False, "message": str(e)})
                except Exception:
                    pass

    def remote_unlock(self):
        """远程解锁：设置时段内解锁 + 关掉锁屏"""
        logging.info("远程解锁")
        self.set_unlocked_for_period(True)
        if self.lock_screen:
            self.lock_screen.unlock()
        else:
            self.unlocked_in_period = True

    def remote_lock(self):
        """远程锁定：等价于手动强制锁定"""
        logging.info("远程锁定")
        self.force_lock()

if __name__ == "__main__":
    app = MainApp()
    app.run()
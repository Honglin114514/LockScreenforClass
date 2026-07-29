import sys
import json
import hashlib
import os
import logging
import string
import subprocess
import win32com.client
import ctypes
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction,
                             QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QMessageBox, QStyle,
                             QDialog, QGridLayout, QFrame,QGraphicsOpacityEffect
                            )
from PyQt5.QtCore import QTimer, Qt, QDateTime, QPropertyAnimation, QEasingCurve, pyqtSignal,QRectF
from PyQt5.QtGui import QPixmap, QPainter , QPainterPath

import win32api
import win32gui
import win32process
import psutil
import qrcode
import win32con
import win32security


# ---------- 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
os.makedirs(BASE_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(BASE_DIR, "lock_config.json")
QR_CODE_FILE = os.path.join(BASE_DIR, "unlock_qrcode.png")

# ---------- 日志 ----------
LOG_FILE = os.path.join(BASE_DIR, "Lock_log.log")
logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# ---------- 配置读写 ----------
def load_config():
    default = {
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
        "password_encrypted": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                for key, value in default.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception as e:
            logging.error(f"配置文件解析失败：{e}")
            return default
    else:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
        return default

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

def get_screen_scale():
    """以1080p高度为基准，返回缩放系数"""
    screen = QApplication.primaryScreen()
    if not screen:
        return 1.0
    height = screen.size().height()
    return height / 1080.0

generate_unlock_qr()

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

# ==================== 锁屏窗口 ====================
class LockScreen(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
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
        bg_path = self.config.get("background", "")
        if bg_path and os.path.exists(bg_path):
            self.bg_label.setPixmap(QPixmap(bg_path))
        else:
            self.bg_label.setStyleSheet("background-color: transparent;")

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
        config = load_config()
        key_filename = config.get("usb_key_file", "unlock.key")
        for drive in string.ascii_uppercase:
            usb_path = f"{drive}:\\{key_filename}"
            if os.path.exists(usb_path):
                logging.info("检测到U盘钥匙，执行完整解锁")
                self.usb_timer.stop()
                self.main_app.set_unlocked_for_period(True)
                self.show_toast("物理密钥解锁成功")
                self.unlock()
                return

    def unlock_with_password(self):
        self.show_buttons_and_reset_timer()
        dialog = PasswordDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            logging.info("密码正确，执行完整解锁")
            self.main_app.set_unlocked_for_period(True)
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
        os.system("shutdown /s /t 0")
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
        QTimer.singleShot(duration, toast.deleteLater)

    def unlock(self):
        logging.info("解锁，开始淡出")
        self.unlock_btn.setEnabled(False)
        self.wb_btn.setEnabled(False)
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
        if self.main_app.is_in_strong_period():
            self.bg_label.setStyleSheet("background-color: black;")
            self.bg_label.setPixmap(QPixmap())
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
        # 先调用父类，确保子控件正常绘制
        super().paintEvent(event)
        
        # 绘制背景图片（如果有）
        if self.bg_pixmap and not self.bg_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            
            # 创建圆角矩形路径（作为裁剪区域）
            rect = self.rect()
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), self.border_radius, self.border_radius)
            painter.setClipPath(path)
            
            # 计算缩放后的图片（保持比例，覆盖整个区域）
            scaled = self.bg_pixmap.scaled(rect.width(), rect.height(),
                                        Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
            # 居中绘制
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

    def get_stylesheet(self):
            return f"""
                QDialog {{ background: transparent;border-radius: {self.border_radius}px; }}
                QLabel {{ color: #333333; font-family: "Microsoft YaHei"; }}
                QPushButton {{
                    background-color: #f0f0f0; color: #333333; border: none;
                    border-radius: {self.btn_border_radius}px;
                    font-size: {self.button_font_size}px; font-weight: bold;
                    min-width: {self.button_min_width}px; min-height: {self.button_min_height}px;
                }}
                QPushButton:hover {{ background-color: #00aaff; color: white; }}
                QPushButton:pressed {{ background-color: #0088cc; }}
                QPushButton#confirmBtn {{ background-color: #00aa66; color: white; }}
                QPushButton#confirmBtn:hover {{ background-color: #00cc77; }}
                QPushButton#cancelBtn {{ background-color: #aa3333; color: white; }}
                QPushButton#cancelBtn:hover {{ background-color: #cc4444; }}
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
                ('回退', 3, 0), ('0', 3, 1), ('清空', 3, 2),
            ]
            for text, row, col in buttons:
                btn = QPushButton(text)
                btn.clicked.connect(self.on_button_clicked)
                grid.addWidget(btn, row, col)
            left_layout.addLayout(grid)

            btn_layout = QHBoxLayout()
            btn_layout.setSpacing(self.spacing)
            confirm_btn = QPushButton("确 认")
            confirm_btn.setObjectName("confirmBtn")
            cancel_btn = QPushButton("取 消")
            cancel_btn.setObjectName("cancelBtn")
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
                tip_label_enc.setStyleSheet(f"font-size: {self.title_font_size}px; color: #888; font-weight: bold;")
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

            right_width = int(self.dialog_width * 0.5)
            total_width = self.dialog_width + right_width + 20
            # 添加透明度效果
            if hasattr(self, 'target_opacity') and self.target_opacity < 1.0:
                effect = QGraphicsOpacityEffect()
                effect.setOpacity(self.target_opacity)
                left_container.setGraphicsEffect(effect)
                right_container.setGraphicsEffect(effect)
            self.setFixedSize(total_width, self.dialog_height)

    def on_button_clicked(self):
            btn = self.sender()
            text = btn.text()
            if text == '回退':
                self.password = self.password[:-1]
            elif text == '清空':
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
        self.anim.setEndValue(self.target_opacity)   # 改为使用保存的透明度
        self.anim.start()
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

        self.setup_tray()
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
            # 重新启用白板按钮，让用户可以再次点击并看到提示
            self.lock_screen.wb_btn.setEnabled(True)
        logging.warning("白板启动超时")

    def check_exemption_status(self):
        """周期性检测豁免软件是否全屏运行（点击白板触发或自动监控）"""
        if not self.exemption_enabled and not self.exemption_wait_timer.isActive():
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
                    win32api.CloseHandle(h_process)
                    return h_token
                except Exception as e:
                    logging.error(f"获取 Explorer 令牌失败 (PID={pid}): {e}")
                    continue
        logging.error("未找到可用的 Explorer 进程")
        return None

    def launch_via_explorer_token(self, exe_path, cmdline=""):
        """使用 Explorer 的令牌启动 EXE，彻底剥离 UIAccess 权限"""
        token = self.get_explorer_token()
        if not token:
            logging.error("无法获取 Explorer 令牌，启动失败")
            return False

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
            win32api.CloseHandle(token)
            logging.info(f"通过 Explorer 令牌成功启动 {exe_path} (PID={dwPid})")
            return True
        except Exception as e:
            logging.error(f"CreateProcessAsUser 调用失败: {e}")
            win32api.CloseHandle(token)
            return False
    
    def show_lock_screen(self):
        if self.lock_screen is None:
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
        for drive in string.ascii_uppercase:
            if os.path.exists(f"{drive}:\\{key}"):
                return True
        return False

    def protected_quit(self):
        config = load_config()
        if config.get("quit_requires_password", True):
            dlg = PasswordDialog()
            if dlg.exec_() == QDialog.Accepted:
                self.quit()
            elif self.check_usb_key_immediate():
                self.quit()
        else:
            self.quit()

    def reload_config(self):
        config = load_config()
        self.whiteboard_max_clicks = config.get("whiteboard_max", 3)
        if self.lock_screen:
            if config.get("enable_shutdown", True):
                self.lock_screen.shutdown_btn.show()
            else:
                self.lock_screen.shutdown_btn.hide()

    def quit(self):
        logging.info("-------退出---------")
        self.exemption_wait_timer.stop()
        self.exemption_monitor_timer.stop()
        if self.lock_screen:
            self.lock_screen.close()
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
    
if __name__ == "__main__":
    app = MainApp()
    app.run()
import sys
import json
import time
import os
import logging
import string
import tempfile
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction,
                             QWidget, QLabel, QPushButton, QVBoxLayout,
                             QHBoxLayout, QMessageBox, QStyle,
                             QDialog, QGridLayout, QFrame,
                             QLineEdit, QSpinBox, QCheckBox, QDialogButtonBox)
from PyQt5.QtCore import QTimer, Qt, QDateTime, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon

import win32api
import win32gui
import win32process
import psutil
import qrcode

# ---------- 安全路径配置 ----------
# 所有数据文件放在程序所在目录（方便调试）
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
os.makedirs(BASE_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(BASE_DIR, "lock_config.json")
LOG_FILE = os.path.join(BASE_DIR, "lock_debug.log")
QR_CODE_FILE = os.path.join(BASE_DIR, "unlock_qrcode.png")

# ---------- 日志 ----------
logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# ---------- 配置读写 ----------
def load_config():
    default = {
        "background": "",
        "periods": [
            {"start": "12:00", "end": "13:00"},
            {"start": "17:00", "end": "18:00"}
        ],
        "strong_periods": [],
        "strong_lock_duration": 30,
        "exam_date": "",
        "password": "114514",
        "usb_key_file": "unlock.key",
        "seewo_path": r"C:\Program Files (x86)\Seewo\EasiNote5\swenlauncher\swenlauncher.exe",
        "enable_shutdown": True,
        "whiteboard_max": 3
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

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# ---------- 二维码 ----------
def generate_unlock_qr():
    config = load_config()
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

        # 背景
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)
        self.load_background()

        # 时间
        self.time_label = QLabel(self)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet(f"color:white; font-size:{self.time_font_size}px; font-weight:bold; font-family:'Microsoft YaHei'; background:transparent;")

        # 日期+星期
        self.date_label = QLabel(self)
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setStyleSheet(f"color:white; font-size:{self.date_font_size}px; font-family:'Microsoft YaHei'; background:transparent;")

        # 倒计时
        self.countdown_label = QLabel(self)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setStyleSheet(f"color:white; font-size:{self.cd_font_size}px; font-family:'Microsoft YaHei'; background:transparent;")

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
                    min-width: {btn_diameter}px;
                    min-height: {btn_diameter}px;
                    max-width: {btn_diameter}px;
                    max-height: {btn_diameter}px;
                }}
                QPushButton:hover {{
                    background: {hover_color};
                }}
            """

        self.unlock_btn = QPushButton("解锁", self)
        self.unlock_btn.setStyleSheet(circle_btn_style("rgba(52,152,219,200)", "rgba(52,152,219,240)"))
        self.unlock_btn.clicked.connect(self.unlock_with_password)

        self.wb_btn = QPushButton("白板", self)
        self.wb_btn.setStyleSheet(circle_btn_style("rgba(46,204,113,200)", "rgba(46,204,113,240)"))
        self.wb_btn.clicked.connect(self.unlock_and_launch)

        self.shutdown_btn = QPushButton("关机", self)
        self.shutdown_btn.setStyleSheet(circle_btn_style("rgba(231,76,60,200)", "rgba(231,76,60,240)"))
        self.shutdown_btn.clicked.connect(self.confirm_shutdown)
        if not self.config.get("enable_shutdown", True):
            self.shutdown_btn.hide()

        # 布局
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)

        # 顶部留白，防止时间贴顶（数值可微调）
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

        # 按钮区（居中偏下）
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.unlock_btn)
        btn_layout.addSpacing(int(30 * scale))
        btn_layout.addWidget(self.wb_btn)
        btn_layout.addSpacing(int(30 * scale))
        btn_layout.addWidget(self.shutdown_btn)
        btn_layout.addStretch(1)
        vbox.addLayout(btn_layout)

        # 按钮下方更大的留白，使其明显偏下而非贴底
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

        # 必须启用鼠标追踪，否则空白区域点击可能无法触发 mousePressEvent
        self.setMouseTracking(True)

        self.raise_()

    def load_background(self):
        bg_path = self.config.get("background", "")
        if bg_path and os.path.exists(bg_path):
            self.bg_label.setPixmap(QPixmap(bg_path))
        else:
            self.bg_label.setStyleSheet("background-color: black;")

    def update_datetime(self):
        now = QDateTime.currentDateTime()
        self.time_label.setText(now.toString("HH:mm:ss"))
        weekdays = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
        wd = weekdays[now.date().dayOfWeek() - 1]
        self.date_label.setText(f"{now.toString('yyyy年M月d日')} {wd}")
        self.update_countdown()

    def update_countdown(self):
        exam_str = self.config.get("exam_date", "")
        today = datetime.now().date()
        try:
            if exam_str:
                exam_date = datetime.strptime(exam_str, "%Y-%m-%d").date()
                delta = (exam_date - today).days
                if delta > 0:
                    self.countdown_label.setText(f"距中考还有 {delta} 天")
                elif delta == 0:
                    self.countdown_label.setText("开始中考")
                else:
                    self.countdown_label.setText("中考已结束")
            else:
                self.countdown_label.setText("中考日期未设置")
        except Exception as e:
            logging.error(f"中考日期解析失败：{e}")
            self.countdown_label.setText("中考日期格式错误")

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
        dialog = self.PasswordDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            logging.info("密码正确，执行完整解锁")
            self.main_app.set_unlocked_for_period(True)
            self.unlock()

    def unlock_and_launch(self):
        self.show_buttons_and_reset_timer()
        logging.info("白板按钮被点击")
        if not self.main_app.try_whiteboard_click():
            self.show_toast("异常的操作！请稍后重试。")
            return
        self.unlock()
        self.main_app.start_incomplete_monitoring()
        config = load_config()
        path = config.get("seewo_path", "")
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                logging.error(f"启动希沃失败: {e}")

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
        if not self.buttons_visible:
            self.unlock_btn.show()
            self.wb_btn.show()
            self.shutdown_btn.show()
            self.buttons_visible = True
        # 重启30秒倒计时（无论之前是否可见）
        self.hide_btn_timer.stop()
        self.hide_btn_timer.start(5000)  # 30秒

    def hide_buttons(self):
        self.unlock_btn.hide()
        self.wb_btn.hide()
        self.shutdown_btn.hide()
        self.buttons_visible = False

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
            self.border_radius = int(20 * scale)
            self.btn_border_radius = int(10 * scale)
            self.spacing = int(20 * scale)
            self.margin = int(40 * scale)
            self.grid_spacing = int(12 * scale)

            self.init_ui()
            self.setStyleSheet(self.get_stylesheet())

        def get_stylesheet(self):
            return f"""
                QDialog {{ background: transparent; }}
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
                    background-color: #ffffff; border: 1px solid #cccccc;
                    border-radius: {self.border_radius}px;
                }}
            """)
            left_layout = QVBoxLayout(left_container)
            left_layout.setSpacing(self.spacing)
            left_layout.setContentsMargins(self.margin, self.margin, self.margin, self.margin)

            title = QLabel("请输入密码")
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet(f"font-size: {self.title_font_size}px; font-weight: bold; color: #333;")
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

            right_container = QFrame(self)
            right_container.setFixedWidth(int(self.dialog_width * 0.5))
            right_container.setObjectName("rightContainer")
            right_container.setStyleSheet(f"""
                QFrame#rightContainer {{
                    background-color: #ffffff; border: 1px solid #cccccc;
                    border-radius: {self.border_radius}px;
                }}
            """)
            right_layout = QVBoxLayout(right_container)
            right_layout.setAlignment(Qt.AlignCenter)
            right_layout.setContentsMargins(self.margin//2, self.margin, self.margin//2, self.margin)

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

            tip_label = QLabel("扫码获取密码")
            tip_label.setAlignment(Qt.AlignCenter)
            tip_label.setStyleSheet(f"font-size: {int(self.title_font_size * 0.6)}px; color: #666; margin-top: 10px;")
            right_layout.addWidget(tip_label)

            main_layout.addWidget(left_container)
            main_layout.addWidget(right_container)

            outer_layout = QVBoxLayout()
            outer_layout.setContentsMargins(0, 0, 0, 0)
            outer_layout.addLayout(main_layout)
            self.setLayout(outer_layout)

            right_width = int(self.dialog_width * 0.5)
            total_width = self.dialog_width + right_width + 20
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
            self.anim.setEndValue(1)
            self.anim.start()
            super().showEvent(event)


# ==================== 强锁窗口 ====================
class StrongLockWindow(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: black;")
        screen = QApplication.primaryScreen()
        self.resize(screen.size())

        scale = screen.size().height() / 1080
        time_font = int(100 * scale)
        date_font = int(30 * scale)
        cd_font = int(30 * scale)

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet(f"color:white; font-size:{time_font}px; font-weight:bold; font-family:'Microsoft YaHei';")
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setStyleSheet(f"color:white; font-size:{date_font}px; font-family:'Microsoft YaHei';")
        self.countdown_label = QLabel()
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setStyleSheet(f"color:white; font-size:{cd_font}px; font-family:'Microsoft YaHei';")

        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignCenter)
        vbox.addWidget(self.time_label)
        vbox.addWidget(self.date_label)
        vbox.addWidget(self.countdown_label)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_clock)
        self.timer.start(1000)
        self.update_clock()

        self.usb_timer = QTimer(self)
        self.usb_timer.timeout.connect(self.check_usb_unlock)
        self.usb_timer.start(1000)

        self.showFullScreen()
        self.raise_()

    def update_clock(self):
        now = QDateTime.currentDateTime()
        self.time_label.setText(now.toString("HH:mm:ss"))
        weekdays = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
        wd = weekdays[now.date().dayOfWeek() - 1]
        self.date_label.setText(f"{now.toString('yyyy年M月d日')} {wd}")
        config = load_config()
        exam_str = config.get("exam_date", "")
        if exam_str:
            try:
                exam = datetime.strptime(exam_str, "%Y-%m-%d").date()
                delta = (exam - datetime.now().date()).days
                if delta > 0:
                    self.countdown_label.setText(f"距离中考还有 {delta} 天")
                elif delta == 0:
                    self.countdown_label.setText("开始中考")
                else:
                    self.countdown_label.setText("中考已结束")
            except:
                self.countdown_label.setText("中考日期错误")
        else:
            self.countdown_label.setText("")

    def check_usb_unlock(self):
        config = load_config()
        key = config.get("usb_key_file", "unlock.key")
        # 仅检测可移动磁盘，避免误判本地硬盘上的同名文件
        for part in psutil.disk_partitions():
            if 'removable' in part.opts.lower():
                drive = part.device
                key_path = os.path.join(drive, key)
                if os.path.exists(key_path):
                    logging.info("强锁窗口检测到U盘钥匙，执行完整解锁")
                    self.usb_timer.stop()
                    self.timer.stop()
                    self.main_app.set_unlocked_for_period(True)
                    self.main_app.end_strong_lock()
                    return
      
    def closeEvent(self, event):
        # 停止自身定时器
        self.usb_timer.stop()
        self.timer.stop()
        # 通知主程序清理强锁状态
        self.main_app.on_strong_lock_closed()
        super().closeEvent(event)


# ==================== 设置窗口 ====================
class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.config = load_config()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("解锁密码"))
        self.pwd_edit = QLineEdit(self.config.get("password", ""))
        layout.addWidget(self.pwd_edit)

        layout.addWidget(QLabel("中考日期 (YYYY-MM-DD)"))
        self.exam_edit = QLineEdit(self.config.get("exam_date", ""))
        layout.addWidget(self.exam_edit)

        layout.addWidget(QLabel("每时段白板最大次数"))
        self.wb_edit = QSpinBox()
        self.wb_edit.setValue(self.config.get("whiteboard_max", 3))
        layout.addWidget(self.wb_edit)

        self.shutdown_cb = QCheckBox("启用关机按钮")
        self.shutdown_cb.setChecked(self.config.get("enable_shutdown", True))
        layout.addWidget(self.shutdown_cb)

        layout.addWidget(QLabel("手动强锁时长 (分钟)"))
        self.strong_dur = QSpinBox()
        self.strong_dur.setValue(self.config.get("strong_lock_duration", 30))
        layout.addWidget(self.strong_dur)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def save(self):
        self.config["password"] = self.pwd_edit.text()
        self.config["exam_date"] = self.exam_edit.text()
        self.config["whiteboard_max"] = self.wb_edit.value()
        self.config["enable_shutdown"] = self.shutdown_cb.isChecked()
        self.config["strong_lock_duration"] = self.strong_dur.value()
        save_config(self.config)
        generate_unlock_qr()
        self.accept()


# ==================== 主控程序 ====================
class MainApp:
    def __init__(self):
        logging.debug("主程序启动")
        import traceback
        def excepthook(exc_type, exc_value, exc_tb):
            logging.critical("未捕获的异常", exc_info=(exc_type, exc_value, exc_tb))
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        sys.excepthook = excepthook

        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.lock_screen = None
        self.unlocked_in_period = False
        self.current_period_end = None

        # 白板计数
        self.whiteboard_click_count = 0
        self.whiteboard_max_clicks = load_config().get("whiteboard_max", 3)
        self.current_period_key = None

        # 强锁相关
        self.strong_lock_window = None
        self.strong_lock_timer = QTimer()
        self.strong_lock_timer.timeout.connect(self.end_strong_lock)
        self._manual_strong_lock = False   # 手动强锁标志

        # 不完整解锁监控
        self.incomplete_unlock = False
        self.incomplete_monitor = QTimer()
        self.incomplete_monitor.timeout.connect(self.check_incomplete_fullscreen)

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
        self.tray.setToolTip("LAZY-CLS")

        menu = QMenu()
        lock_action = QAction("立即锁定", menu)
        lock_action.triggered.connect(self.force_lock)
        strong_lock_action = QAction("强锁", menu)
        strong_lock_action.triggered.connect(lambda checked=False: self.start_strong_lock())
        settings_action = QAction("设置", menu)
        settings_action.triggered.connect(self.open_settings)
        clear_log_action = QAction("清理日志", menu)
        clear_log_action.triggered.connect(self.clear_log)
        about_action = QAction("关于", menu)
        about_action.triggered.connect(self.show_about)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.protected_quit)

        menu.addAction(lock_action)
        menu.addAction(strong_lock_action)
        menu.addAction(settings_action)
        menu.addAction(clear_log_action)
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
        logging.debug(f"设置 unlocked_in_period = {unlocked}")

    def should_show_lock(self):
        if not self.is_in_lock_period():
            return False
        if self.unlocked_in_period:
            return False
        if self.is_seewo_running():
            return False
        return True

    def update_lock_screen(self):
        should_show = self.should_show_lock()
        if should_show and self.lock_screen is None:
            self.show_lock_screen()
        elif not should_show and self.lock_screen is not None:
            self.hide_lock_screen()

    def check_time(self):
        # 如果手动强锁正在进行中，则不要自动干预
        if self._manual_strong_lock and self.strong_lock_window is not None:
            # 手动强锁期间，隐藏普通锁屏
            if self.lock_screen:
                self.hide_lock_screen()
            return

        # 强锁时段自动处理
        if self.is_in_strong_period():
            if self.strong_lock_window is None:
                self.start_strong_lock(auto=True)
            if self.lock_screen:
                self.hide_lock_screen()
            return
        else:
            if self.strong_lock_window and not self._manual_strong_lock:
                self.end_strong_lock()

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

    def is_seewo_running(self):
        target_processes = ["EasiNote.exe", "EasiCamera.exe"]
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
                if proc_name in target_processes:
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top, right, bottom = rect
                    width = right - left
                    height = bottom - top
                    if width >= screen_width * 0.98 and height >= screen_height * 0.98:
                        return True
            except:
                continue
        return False

    def try_whiteboard_click(self):
        if self.whiteboard_click_count >= self.whiteboard_max_clicks:
            return False
        self.whiteboard_click_count += 1
        if self.whiteboard_click_count >= self.whiteboard_max_clicks and self.lock_screen:
            self.lock_screen.wb_btn.setEnabled(False)
        return True

    def start_incomplete_monitoring(self):
        self.incomplete_unlock = True
        self.incomplete_monitor.start(6000)

    def check_incomplete_fullscreen(self):
        if not self.incomplete_unlock:
            return
        if not self.is_seewo_running():
            logging.info("不完整解锁：希沃退出全屏，重新锁定")
            self.incomplete_unlock = False
            self.incomplete_monitor.stop()
            self.force_lock()

    def show_lock_screen(self):
        if self.lock_screen is None:
            self.lock_screen = LockScreen(main_app=self)
            self.lock_screen.show()
            self.lock_screen.raise_()
            self.lock_screen.activateWindow()
            
            # 淡入动画
            self.fade_in = QPropertyAnimation(self.lock_screen, b"windowOpacity")
            self.fade_in.setDuration(300)
            self.fade_in.setStartValue(0.0)
            self.fade_in.setEndValue(1.0)
            self.fade_in.setEasingCurve(QEasingCurve.OutCubic)
            self.fade_in.start()
            # 将动画对象挂靠在窗口上，防止被过早回收
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
            # 关键：保留动画引用，防止被过早回收
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

    def start_strong_lock(self, duration_minutes=None, auto=False):
        if duration_minutes is None:
            duration_minutes = load_config().get("strong_lock_duration", 30)
        if not auto:
            self._manual_strong_lock = True
        else:
            self._manual_strong_lock = False

        if self.strong_lock_window is None:
            self.strong_lock_window = StrongLockWindow(self)
            self.strong_lock_window.show()
            self.strong_lock_window.raise_()
            # 只有手动强锁才启动倒计时关闭定时器
            if not auto:
                logging.info(f"强锁定时器启动，时长 = {duration_minutes} 分钟")
                self.strong_lock_timer.start(duration_minutes * 60000)
        if self.strong_lock_window is not None and not self.strong_lock_window.isVisible():
            self.on_strong_lock_closed()

    def end_strong_lock(self, force_close=False):
        self.strong_lock_timer.stop()
        if self.strong_lock_window:
            # 只要是手动强锁结束或强制关闭，就直接关窗
            self.strong_lock_window.close()
        else:
            self.on_strong_lock_closed()

    def clear_log(self):
        try:
            time.sleep(1)
            os.remove(LOG_FILE)
            logging.info("日志已清理")
        except:
            pass

    def show_about(self):
        QMessageBox.about(None, "关于",
            "========================================\n"
            "Lock Screen for Class\n"
            "========================================\n"
            "版本 v0.1.0 测试预览\n"
            "作者：起懒了的cat (Honglin114514)\n"
            "========================================\n"
            "特别鸣谢：\n"
            "本软件使用了 getti 库\n"
            "========================================\n"
            "使用即代表同意我们的用户协议（详见仓库版本发布说明），最终解释权归作者所有。\n"
            "用户使用此程序产生的所有后果由使用者承担.\n")

    def check_usb_key_immediate(self):
        config = load_config()
        key = config.get("usb_key_file", "unlock.key")
        for drive in string.ascii_uppercase:
            if os.path.exists(f"{drive}:\\{key}"):
                return True
        return False

    def protected_quit(self):
        dlg = LockScreen.PasswordDialog()
        if dlg.exec_() == QDialog.Accepted:
            self.quit()
        elif self.check_usb_key_immediate():
            self.quit()

    def open_settings(self):
        dlg = LockScreen.PasswordDialog()
        if dlg.exec_() == QDialog.Accepted:
            settings = SettingsWindow()
            settings.exec_()
            self.reload_config()
        elif self.check_usb_key_immediate():
            settings = SettingsWindow()
            settings.exec_()
            self.reload_config()

    def reload_config(self):
        config = load_config()
        self.whiteboard_max_clicks = config.get("whiteboard_max", 3)
        if self.lock_screen:
            if config.get("enable_shutdown", True):
                self.lock_screen.shutdown_btn.show()
            else:
                self.lock_screen.shutdown_btn.hide()

    def quit(self):
        logging.info("用户退出程序")
        if self.lock_screen:
            self.lock_screen.close()
        self.app.quit()

    def run(self):
        self.app.exec_()

    def on_strong_lock_closed(self):
        """强锁窗口关闭时调用（无论哪种方式）"""
        self.strong_lock_timer.stop()
        self.strong_lock_window = None
        self._manual_strong_lock = False
        # 如果需要，根据当前时段恢复普通锁屏
        self.update_lock_screen()

if __name__ == "__main__":
    app = MainApp()
    app.run()

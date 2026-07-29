# setting.pyw
import sys
import os
import json
import subprocess
import psutil
import logging
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import QUrl, Qt, QObject, pyqtSlot, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

#切换工作目录
def get_base_dir():
    """获取程序实际运行目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

# ---------- 配置 ----------
BASE_DIR = get_base_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "lock_config.json")

# ---------- 日志 ----------
LOG_FILE = os.path.join(BASE_DIR, "Lock_setting_log.log")
logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

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
        except:
            logging.error("配置文件解析失败：{e}")
            return default
    else:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
        return default

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# ---------- JS 桥接 ----------
class Bridge(QObject):
    configChanged = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.window = None

    # ---------- 开机自启辅助方法 ----------
    def _get_main_program_path(self):
        bat_path = os.path.join(BASE_DIR, "start.bat")
        if os.path.exists(bat_path):
            return bat_path
        return None

    # ---------- JS 调用接口 ----------
    @pyqtSlot(str, result=str)
    def get(self, key):
        return json.dumps(self.config.get(key, None))

    @pyqtSlot(result=str)
    def getAll(self):
        return json.dumps(self.config)

    @pyqtSlot(str, str)
    def set(self, key, value):
        try:
            parsed = json.loads(value)
        except:
            parsed = value

        # ---------- 密码加密开关 ----------
        if key == 'password_encrypted':
            # 更新开关状态
            self.config['password_encrypted'] = parsed
            # 如果启用加密且当前密码存在且不是哈希格式（64位十六进制），则加密
            if parsed:
                current_pwd = self.config.get('password', '')
                if current_pwd and not (len(current_pwd) == 64 and all(c in '0123456789abcdef' for c in current_pwd.lower())):
                    import hashlib
                    self.config['password'] = hashlib.sha256(current_pwd.encode('utf-8')).hexdigest()
            save_config(self.config)
            self.configChanged.emit(self.config)
            return

        # ---------- 密码字段 ----------
        if key == 'password':
            if self.config.get('password_encrypted', True):
                import hashlib
                hashed = hashlib.sha256(parsed.encode('utf-8')).hexdigest()
                self.config[key] = hashed
            else:
                self.config[key] = parsed
            save_config(self.config)
            self.configChanged.emit(self.config)
            return

        # ---------- 普通字段 ----------
        self.config[key] = parsed
        save_config(self.config)
        self.configChanged.emit(self.config)

    @pyqtSlot(str)
    def setAll(self, json_str):
        try:
            new_config = json.loads(json_str)
            for key, value in new_config.items():
                self.config[key] = value
            save_config(self.config)
            self.configChanged.emit(self.config)
            return "success"
        except Exception as e:
            return str(e)

    @pyqtSlot(str, result=str)
    def pickFile(self, key):
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "选择文件",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*.*)"
        )
        if file_path:
            self.config[key] = file_path
            save_config(self.config)
            self.configChanged.emit(self.config)
            return file_path
        return ""

    @pyqtSlot(str, result=bool)
    def verify_password(self, pwd):
        correct = self.config.get('password', '')
        if self.config.get('password_encrypted', True):
            import hashlib
            hashed = hashlib.sha256(pwd.encode('utf-8')).hexdigest()
            return hashed == correct
        else:
            return pwd == correct

    @pyqtSlot()
    def run_period_editor(self):
        import subprocess
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'classislandtolockscreen.py')
        if os.path.exists(script_path):
            try:
                subprocess.Popen([sys.executable, script_path], shell=True)
            except Exception as e:
                print(f"启动失败: {e}")
        else:
            print("文件不存在")

    @pyqtSlot(result=str)
    def get_themes(self):
        themes_dir = os.path.join(BASE_DIR, 'themes')
        if not os.path.exists(themes_dir):
            return json.dumps([])
        themes = [d for d in os.listdir(themes_dir) 
                  if os.path.isdir(os.path.join(themes_dir, d))]
        return json.dumps(themes)

    @pyqtSlot(str)
    def apply_theme(self, theme_name):
        themes_dir = os.path.join(BASE_DIR, 'themes')
        theme_path = os.path.join(themes_dir, theme_name, 'config.json')
        if not os.path.exists(theme_path):
            return
        try:
            with open(theme_path, 'r', encoding='utf-8') as f:
                theme_config = json.load(f)
            personal_keys = [
                'clock_color', 'shutdown_color', 'shutdown_hover_color',
                'unlock_color', 'whiteboard_color', 'shutdown_text',
                'unlock_text', 'whiteboard_text', 'settings_background',
                'password_opacity', 'background', 'password_bg'
            ]
            for key in personal_keys:
                if key in theme_config:
                    self.config[key] = theme_config[key]
            save_config(self.config)
            self.configChanged.emit(self.config)
        except Exception as e:
            print(f"应用主题失败: {e}")

    @pyqtSlot(result=str)
    def import_classisland_periods(self):
        from classisland_importer import import_periods
        success, msg = import_periods()
        if success:
            self.config = load_config()
            self.configChanged.emit(self.config)
        return msg

    @pyqtSlot(result=str)
    def get_classisland_profiles(self):
        from classisland_importer import find_classisland_dir, find_profile_files, find_default_json
        install_dir = find_classisland_dir()
        if not install_dir:
            return json.dumps([])
        profiles = find_profile_files(install_dir)
        if not profiles:
            default = find_default_json(install_dir)
            if default:
                profiles = [default]
        result = []
        for path in profiles:
            name = os.path.basename(path)
            result.append({"name": name, "path": path})
        return json.dumps(result)

    @pyqtSlot(str)
    def import_classisland_periods_from_profile(self, profile_path):
        from classisland_importer import extract_break_periods
        try:
            periods = extract_break_periods(profile_path)
            lock_path = os.path.join(BASE_DIR, 'lock_config.json')
            with open(lock_path, 'r', encoding='utf-8') as f:
                lock_data = json.load(f)
            lock_data["periods"] = periods
            with open(lock_path, 'w', encoding='utf-8') as f:
                json.dump(lock_data, f, ensure_ascii=False, indent=4)
            self.config = load_config()
            self.configChanged.emit(self.config)
            return f"成功导入 {len(periods)} 个时段"
        except Exception as e:
            return f"导入失败: {str(e)}"
        
    @pyqtSlot(result=bool)
    def is_app_running(self):
        """检查主程序是否运行"""
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == 'lockscreenforclass.exe':
                    return True
            except:
                continue
        return False

    @pyqtSlot()
    def restart_app(self):
        """结束主程序进程重启"""
        import time
        # 结束所有 lockscreenforclass.exe 进程
        killed = False
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == 'lockscreenforclass.exe':
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if killed:
            time.sleep(1)  # 等待进程完全退出
        # 启动 start.bat
        bat_path = os.path.join(BASE_DIR, 'start.bat')
        if os.path.exists(bat_path):
            #新进程独立于当前窗口
            subprocess.Popen([bat_path], shell=True, cwd=BASE_DIR,
                            creationflags=subprocess.CREATE_NEW_CONSOLE)
            print("已尝试重新启动主程序")
        else:
            print("警告: start.bat 不存在")

# ---------- 主窗口 ----------
class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("设置")
        self.resize(960, 680)
        self.setMinimumSize(800, 600)

        self.webview = QWebEngineView()
        self.webview.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.webview.focusInEvent = lambda e: self.webview.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.webview.setUrl(QUrl.fromLocalFile(
            os.path.join(BASE_DIR, "setting.html")
        ))

        self.bridge = Bridge()
        self.bridge.window = self

        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.webview.page().setWebChannel(self.channel)

        self.webview.loadFinished.connect(self.on_load_finished)

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.webview)
        self.setCentralWidget(central_widget)

    def on_load_finished(self):
        self.webview.page().runJavaScript("""
            if (typeof bridge === 'undefined') {
                bridge = {
                    get: function(key) {
                        return new Promise((resolve) => {
                            new QWebChannel(qt.webChannelTransport, function(channel) {
                                channel.objects.bridge.get(key, function(result) {
                                    resolve(JSON.parse(result));
                                });
                            });
                        });
                    },
                    getAll: function() {
                        return new Promise((resolve) => {
                            new QWebChannel(qt.webChannelTransport, function(channel) {
                                channel.objects.bridge.getAll(function(result) {
                                    resolve(JSON.parse(result));
                                });
                            });
                        });
                    },
                    set: function(key, value) {
                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            channel.objects.bridge.set(key, JSON.stringify(value));
                        });
                    },
                    setAll: function(config) {
                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            channel.objects.bridge.setAll(JSON.stringify(config));
                        });
                    }
                };
                console.log('Bridge 已注入');
            }
        """)


# ---------- 入口 ----------
def main():
    logging.info("初始化完成，主程序启动")
    def excepthook(exc_type, exc_value, exc_tb):
        logging.critical("未捕获的异常", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = excepthook
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    window = SettingsWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
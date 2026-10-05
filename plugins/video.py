# -*- coding: utf-8 -*-
"""
dynamic_wallpaper.py —— 独立可测试的动态壁纸模块

设计原则
========
1. 完全独立：不引用主程序任何东西，可以单独运行、单独调试
2. 不透明窗口 + QVideoWidget → 走硬件解码路径，CPU 占用极低
3. 生命周期由调用方（MainApp）控制，本模块不做任何调度

对外 API
========
    wallpaper = DynamicWallpaper("path/to/video.mp4", muted=True)
    wallpaper.start()      # 显示并循环播放，返回是否成功
    wallpaper.pause()      # 暂停（保留窗口、保留位置）
    wallpaper.resume()     # 从暂停恢复
    wallpaper.stop()       # 停止播放、隐藏窗口、位置归零
    wallpaper.release()    # 完全卸载媒体（程序退出时调用）
    wallpaper.is_running()
    wallpaper.set_muted(bool)
    wallpaper.set_video(path)   # 切换视频源

单独测试
========
    python dynamic_wallpaper.py <视频文件路径>
"""

import os
import sys
import logging

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget


class DynamicWallpaper(QWidget):
    """全屏视频壁纸窗口（不透明，独立于锁屏窗口）。"""

    def __init__(self, video_path, muted=True,
                 aspect_mode=Qt.KeepAspectRatio):
        """
        :param video_path:  视频文件路径
        :param muted:       是否静音（教室场景默认 True）
        :param aspect_mode: Qt.KeepAspectRatio（保持比例，可能黑边）
                            Qt.IgnoreAspectRatio（拉伸铺满，可能变形）
        """
        super().__init__()
        self._video_path = video_path
        self._muted = muted

        # ---------- 窗口属性 ----------
        # 关键：不加 WA_TranslucentBackground
        #   → 走不透明渲染路径，QVideoWidget 启用硬件直通
        #   → 解码在 GPU，帧直接送显示合成器，CPU 几乎不参与
        # Qt.Tool → 不出现在任务栏
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)

        # ---------- 视频组件 ----------
        self._video_widget = QVideoWidget(self)
        self._video_widget.setAspectRatioMode(aspect_mode)
        self._video_widget.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._video_widget)

        # ---------- 播放器 ----------
        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._video_widget)
        self._player.setVolume(0 if muted else 100)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.error.connect(self._on_error)

        # ---------- 内部状态 ----------
        self._media_loaded = False   # 是否已经 setMedia
        self._running = False        # 是否处于 start 之后、stop 之前

    # ==================== 公开 API ====================
    def start(self):
        """显示窗口并开始播放。首次调用会加载视频。返回是否成功。"""
        if not self._check_source():
            return False

        if not self._media_loaded:
            self._player.setMedia(
                QMediaContent(QUrl.fromLocalFile(self._video_path)))
            self._media_loaded = True
            logging.info(f"[DynamicWallpaper] 加载媒体: {self._video_path}")

        self._fit_to_primary_screen()
        self.show()
        self._player.play()
        self._running = True
        logging.debug("[DynamicWallpaper] start")
        return True

    def stop(self):
        """停止播放并隐藏窗口。位置归零，下次从头播。"""
        self._player.pause()   # QMediaPlayer.stop 会自动 position=0
        self.hide()
        self._running = False
        logging.debug("[DynamicWallpaper] stop")

    def pause(self):
        """暂停，不隐藏窗口。用于强时段等场景。"""
        if self._running:
            self._player.pause()
            logging.debug("[DynamicWallpaper] pause")

    def resume(self):
        """从暂停恢复。"""
        if self._running:
            self._player.play()
            logging.debug("[DynamicWallpaper] resume")

    def release(self):
        """彻底卸载媒体。程序退出时调用。"""
        try:
            self._player.stop()
            self._player.setMedia(QMediaContent())   # 释放解码器
            self._media_loaded = False
            self.hide()
            self._running = False
        except Exception as e:
            logging.error(f"[DynamicWallpaper] release 出错: {e}")
        logging.info("[DynamicWallpaper] released")

    def is_running(self):
        return self._running

    def set_muted(self, muted):
        self._muted = muted
        self._player.setVolume(0 if muted else 100)

    def set_video(self, path):
        """切换视频源。会重新加载媒体。"""
        was_running = self._running
        self._player.stop()
        self._player.setMedia(QMediaContent())
        self._media_loaded = False
        self._video_path = path
        if was_running:
            self.start()

    # ==================== 内部逻辑 ====================
    def _check_source(self):
        if not self._video_path:
            logging.warning("[DynamicWallpaper] 视频路径为空")
            return False
        if not os.path.exists(self._video_path):
            logging.warning(
                f"[DynamicWallpaper] 视频不存在: {self._video_path}")
            return False
        return True

    def _fit_to_primary_screen(self):
        """贴合主屏全屏。多屏场景下始终跟随主屏。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        self.setGeometry(screen.geometry())

    def _on_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            # 循环：从当前位置（末尾）回到开头继续
            self._player.setPosition(0)
            self._player.play()
        elif status == QMediaPlayer.InvalidMedia:
            logging.error(
                f"[DynamicWallpaper] 无法播放媒体: {self._video_path}")

    def _on_error(self, error):
        if error != QMediaPlayer.NoError:
            logging.error(
                f"[DynamicWallpaper] 播放器错误: {self._player.errorString()}")


# ==================== 独立测试入口 ====================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(message)s")

    if len(sys.argv) < 2:
        print("用法: python dynamic_wallpaper.py <视频文件路径>")
        sys.exit(1)

    app = QApplication(sys.argv)

    wallpaper = DynamicWallpaper(sys.argv[1], muted=True)
    if wallpaper.start():
        print(f"正在播放: {sys.argv[1]}")
        print("按 Ctrl+C 或关闭终端退出")
    else:
        print("启动失败，请检查视频路径")
        sys.exit(1)

    sys.exit(app.exec_())
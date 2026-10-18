# 持有本窗口托盘入口，隐藏不释放业务 owner，明确退出仍走主窗口收尾。
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon


class TrayController(QObject):
    def __init__(self, window, *, available=None):
        super().__init__(window)
        self.window = window
        self._available = available or QSystemTrayIcon.isSystemTrayAvailable
        self._notified = False
        self._closed = False
        self.menu = QMenu(window)
        self.menu.addAction("打开 Calc", self.restore)
        self.menu.addSeparator()
        self.menu.addAction("退出 Calc", self.request_exit)
        icon = window.windowIcon()
        if icon.isNull():
            icon = window.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("NTE Drive Calc")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        if self._available():
            self.tray.show()

    def hide_window(self):
        if self._closed:
            return
        if not self._available():
            # 托盘不可用时保留任务栏入口，防止留下用户无法唤回的后台窗口。
            self.window.showMinimized()
            return
        self.tray.show()
        self.window.hide()
        if not self._notified:
            self._notified = True
            self.tray.showMessage("Calc 已在后台运行", "右键托盘图标可打开或退出 Calc。")

    def restore(self):
        if self._closed:
            return
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def request_exit(self):
        if not self._closed:
            # 先恢复窗口：退出确认/保存失败可见；取消退出后窗口继续可用。
            self.restore()
            self.window.close()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.restore()

    def close(self):
        self._closed = True
        self.tray.hide()
        self.menu.close()

# 队伍成员共用头像按钮，显示名仅用于展示，选择始终绑定正式角色身份。
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QToolButton, QWidget

from src.app.theme import themed_style
from src.ui.role_portrait import custom_role_portrait


def role_button(role=None, *, parent=None, checkable=False):
    button = QToolButton(parent)
    button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    button.setIconSize(QSize(36, 36))
    button.setMinimumSize(140, 58)
    button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    button.setCheckable(checkable)
    button.setFocusPolicy(Qt.StrongFocus)
    button.setStyleSheet(themed_style(
        "QToolButton{background:#161b22;color:#c9d1d9;border:1px solid #30363d;"
        "border-radius:8px;padding:7px;font-size:13px;font-weight:600;}"
        "QToolButton:hover{border-color:#58a6ff;}"
        "QToolButton:checked{background:#1f6feb;color:#ffffff;border:2px solid #58a6ff;}"
        "QToolButton:focus{border:2px solid #58a6ff;}"
        "QToolButton:disabled{color:#6e7681;background:#0d1117;border-color:#30363d;}"
    ))
    set_role(button, role)
    return button


def set_role(button, role):
    if role is None:
        button.setText("＋ 待选择")
        button.setIcon(QIcon())
        return
    button.setText(role.name)
    button.setToolTip(role.name)
    button.setAccessibleName(role.name)
    icon = QIcon(custom_role_portrait(72, button.devicePixelRatioF())) if role.custom else QIcon(role.icon_path)
    button.setIcon(icon)


class MemberSlots(QWidget):
    """四个成员位置随可用宽度换行，不把弹窗最小宽度撑出屏幕。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.buttons = [role_button(parent=self) for _ in range(4)]
        self._columns = 0
        # 隐藏控件初始宽度只有 100px；先用两列，避免四行的最小高度撑大弹窗。
        self._reflow(columns=2)

    def _reflow(self, columns=None):
        columns = columns or max(1, min(4, (self.width() + 8) // 148))
        if columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for index, button in enumerate(self.buttons):
            self.grid.addWidget(button, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

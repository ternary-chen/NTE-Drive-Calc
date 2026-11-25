# 构建工具页实验神经渲染入口，沿用三主题卡片与键盘按钮。
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from src.app.theme import themed_style


def build_neural_entry(parent, open_tool):
    row = QFrame(parent)
    row.setObjectName('toolboxNeuralRenderingRow')
    row.setMinimumHeight(94)
    row.setStyleSheet(themed_style(
        'QFrame#toolboxNeuralRenderingRow{background:#161b22;border:1px solid #30363d;border-radius:10px;}'
        'QFrame#toolboxNeuralRenderingRow:hover{background:#1c2128;border-color:#58a6ff;}'))
    layout = QHBoxLayout(row)
    layout.setContentsMargins(18, 12, 16, 12)
    copy = QVBoxLayout()
    title = QLabel('DLSS 神经渲染（实验）', row)
    title.setStyleSheet(themed_style('font-size:16px;font-weight:800;color:#58a6ff;'))
    copy.addWidget(title)
    description = QLabel('获取并检测 ReShade 与 RenoDX 组件，配置后进入游戏实测；支持恢复本次修改。', row)
    description.setWordWrap(True)
    description.setStyleSheet(themed_style('color:#8b949e;font-size:12px;'))
    copy.addWidget(description)
    layout.addLayout(copy, 1)
    button = QPushButton('配置', row)
    button.setObjectName('toolboxNeuralRendering')
    button.setAccessibleName('配置 DLSS 神经渲染实验组件')
    button.setMinimumSize(76, 38)
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(themed_style(
        'QPushButton{background:#d6f0ff;color:#0b3150;border:1px solid #79c0ff;border-radius:7px;padding:6px 16px;}'
        'QPushButton:hover{background:#b6e3ff;}QPushButton:focus{border:2px solid #58a6ff;}'
        'QPushButton:disabled{background:#21262d;color:#8b949e;border-color:#30363d;}'))
    button.clicked.connect(open_tool)
    layout.addWidget(button)
    return row

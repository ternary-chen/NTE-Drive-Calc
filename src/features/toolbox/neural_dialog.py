# 展示第三方神经渲染的实验接入步骤，文件配置不冒充游戏内生效。
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from src.domain.localization.catalog import localized_text
from src.app.window_geometry import fit_dialog_to_available_screen
from src.features.toolbox.neural_controller import NeuralController
from src.integrations.components.neural_profile import SOURCES, PROFILE_LABEL


class NeuralRenderingDialog(QDialog):
    def __init__(self, dependencies, parent=None):
        super().__init__(parent)
        self.setWindowTitle('DLSS 神经渲染（实验）')
        self.setWindowModality(Qt.ApplicationModal)
        self.setObjectName('neuralRenderingDialog')
        self.busy = False
        self.dependencies = dependencies
        self.controller = NeuralController(dependencies, self)
        layout = QVBoxLayout(self)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        content = QWidget(area)
        form = QVBoxLayout(content)
        area.setWidget(content)
        layout.addWidget(area)
        description = QLabel('通过 ReShade + RenoDX 接入第三方神经渲染。\n'
            '当前是待实测方案：先关闭游戏，配置后到游戏内开启，再检查同步、战报和 HUD。', content)
        description.setWordWrap(True)
        form.addWidget(description)
        profile = QLabel(PROFILE_LABEL + '\n版本和串联配置由 Calc 核对，不接受任意混搭。', content)
        profile.setWordWrap(True)
        form.addWidget(profile)
        links = QHBoxLayout()
        for label, url in SOURCES:
            button = QPushButton(label, content)
            button.clicked.connect(lambda checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            links.addWidget(button)
        form.addLayout(links)
        help_text = QLabel('1. 点击“打开组件目录”，把自行下载的文件放进去。\n'
            '2. 本轮接受 ReShade 6.8.0 Add-on 安装包、ShortFuse DLSS 插件（2026-10-17）和 NR 310.9.16 运行库 ZIP。\n'
            '3. 点击检测后配置，也可选择其他目录或已解压的三个 DLL/插件文件。\n'
            '安装包只读取内部文件，不会执行；不需要另装 Bridge 或 Feeder。', content)
        help_text.setWordWrap(True)
        form.addWidget(help_text)
        row = QHBoxLayout()
        self.folder = QLineEdit(content)
        self.folder.setPlaceholderText('组件目录：支持候选安装包、ZIP 或已解压文件')
        self.folder.setAccessibleName('神经渲染组件文件夹')
        if dependencies.component_directory is not None:
            self.folder.setText(str(dependencies.component_directory))
            self.folder.setCursorPosition(0)
        self.folder.setToolTip(self.folder.text())
        self.folder.textChanged.connect(self.folder.setToolTip)
        row.addWidget(self.folder, 1)
        self.browse = QPushButton('选择文件夹', content)
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.browse)
        self.open_directory = QPushButton('打开组件目录', content)
        self.open_directory.clicked.connect(self.controller.open_directory)
        row.addWidget(self.open_directory)
        form.addLayout(row)
        actions = QHBoxLayout()
        self.detect = QPushButton('检测', content)
        self.detect.clicked.connect(lambda: self.controller.inspect(self.folder.text().strip()))
        self.configure = QPushButton('配置实验组件', content)
        self.configure.clicked.connect(lambda: self.controller.prepare(self.folder.text().strip()))
        self.restore = QPushButton('恢复本次配置', content)
        self.restore.clicked.connect(self._restore)
        for button in (self.detect, self.configure, self.restore):
            actions.addWidget(button)
        form.addLayout(actions)
        self.status = QTextEdit(content)
        self.status.setReadOnly(True)
        self.status.setAccessibleName('神经渲染检测和操作结果')
        self.status.setMinimumHeight(140)
        self.status.setPlainText('尚未检测。请先选择组件目录。\n需要中风险或开发模式，且 Calc 原生组件已部署。\n'
            '配置完成不等于 DLSS 5 已生效；本工具不会启动游戏或自动录制战报。')
        form.addWidget(self.status, 1)
        note = QLabel('首次配置会备份受影响文件。已有其他代理或另一套 DLSS 插件时停止；'
            '恢复只撤销本次修改，遇到玩家更新的文件会保留并提示。\n'
            '如果无法启动、黑屏或闪烁，请退出游戏后恢复本次配置。', content)
        note.setWordWrap(True)
        form.addWidget(note)
        bottom = QHBoxLayout()
        self.settings_button = QPushButton('打开环境设置', self)
        self.settings_button.clicked.connect(self._settings)
        bottom.addWidget(self.settings_button)
        bottom.addStretch()
        self.close_button = QPushButton('关闭', self)
        self.close_button.clicked.connect(self.reject)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        self.controller.busy_changed.connect(self._busy)
        self.controller.message.connect(self.status.setPlainText)
        self.controller.prepared.connect(self._confirm_plan)
        self.controller.directory_ready.connect(self._open_directory)
        fit_dialog_to_available_screen(self, QSize(760, 620))

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, '选择神经渲染组件目录', self.folder.text())
        if folder:
            self.folder.setText(folder)
            self.controller.inspect(folder)

    def _open_directory(self, directory):
        self.folder.setText(directory)
        if QDesktopServices.openUrl(QUrl.fromLocalFile(directory)):
            self.status.setPlainText('组件目录已打开。把下载文件放入后，回到这里点击“检测”。')
        else:
            self.status.setPlainText(localized_text(
                    None, 'toolbox.dlss.neural_dialog.t599fd3c5',
                    '无法打开文件管理器，请手动前往：{directory}',
                    directory=directory,
                ))

    def _busy(self, busy):
        self.busy = busy
        for widget in (self.folder, self.browse, self.open_directory, self.detect, self.configure, self.restore,
                       self.settings_button, self.close_button):
            widget.setEnabled(not busy)
        if busy:
            self.status.setPlainText('正在核对或处理组件，请保持游戏关闭…')

    def _confirm(self, text, details=''):
        message = QMessageBox(QMessageBox.Warning, '确认实验配置', text,
                             QMessageBox.Ok | QMessageBox.Cancel, self)
        message.setDefaultButton(QMessageBox.Cancel)
        if details:
            message.setDetailedText(details)
        fit_dialog_to_available_screen(message, QSize(600, 260))
        QApplication.beep()
        return message.exec() == QMessageBox.Ok

    def _confirm_plan(self, prepared):
        # PageCommitLane 已物理收尾；延迟到 settled 之后再打开确认或派发写操作。
        from PySide6.QtCore import QTimer
        def confirm():
            if self.controller.closing:
                return
            if self._confirm('将配置 ReShade 串联及 RenoDX 神经渲染组件，并保存恢复副本。\n'
                             '游戏必须保持关闭；进入游戏后仍需实测。', prepared[0].summary):
                self.controller.apply(prepared)
            else:
                self.status.setPlainText('已取消，未配置游戏文件。')
        QTimer.singleShot(0, self, confirm)

    def _restore(self):
        if self._confirm('退出游戏后恢复本工具修改的文件。\n玩家后来改动的组件不会被强行覆盖。'):
            self.controller.restore()

    def _settings(self):
        self.reject()
        self.dependencies.settings()

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def shutdown(self):
        self.controller.close()
        self.hide()

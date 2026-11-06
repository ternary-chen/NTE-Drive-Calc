# 首次使用时后台评估默认评级，仅显示可取消进度，不恢复角色选择页面。
from threading import Event
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout
from src.app.page_tasks import PageRequest, PageTaskLane
from src.app.window_geometry import fit_dialog_to_available_screen


class RuleGenerationProgress(QDialog):
    def __init__(self,parent,*,build):
        super().__init__(parent)
        self.setWindowTitle('首次推荐驱动保留评级')
        self.generated = None
        self._cancel = Event()
        self._closing = False
        self._ready = False
        self._lane = PageTaskLane(self)
        self._lane.idle.connect(self._idle)
        layout = QVBoxLayout(self)
        self.status = QLabel('正在读取仓库评分，按蓝图平均需求选取质量样本…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0,0)
        layout.addWidget(self.progress)
        self.cancel = QPushButton('取消')
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)
        fit_dialog_to_available_screen(self,QSize(460,180))
        self._lane.submit(PageRequest(object(),lambda:build(cancel_check=self._cancel.is_set),self._receive,self._error))

    def _receive(self,result):
        self.generated = result
        self._ready = True

    def _error(self,message):
        self.generated = None
        self.status.setText(message)
        self.progress.hide()
        self.cancel.setText('关闭')

    def is_running(self):
        return self._lane.is_running()

    def _idle(self):
        if self._closing:
            super().reject()
        elif self._ready:
            self.accept()

    def reject(self):
        self._cancel.set()
        if self.is_running():
            self._closing = True
            self._lane.cancel()
            self.status.setText('正在取消，等待本次评估结束…')
        else:
            super().reject()

    def closeEvent(self,event):
        if self.is_running():
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)

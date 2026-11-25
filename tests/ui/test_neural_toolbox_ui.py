# 验证实验入口、离屏检测和确认取消行为，不操作真实游戏或桌面。
import os
import time
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from src.features.toolbox.neural_controller import NeuralDependencies
from src.features.toolbox.neural_dialog import NeuralRenderingDialog
from src.features.toolbox.page import ToolboxPage
from src.features.toolbox.toolbox_navigation import ToolboxDependencies


def finish(app, condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert condition()


def test_tool_card_opens_experiment_and_detects_without_mutation():
    app = QApplication.instance() or QApplication([])
    mutations = []
    service = SimpleNamespace(inspect=lambda folder: '尚未配置，驱动兼容性未验证', close=lambda: None)
    neural = NeuralDependencies(lambda: service, lambda: mutations.append('begin'), lambda *_: None,
                                lambda *_: None, lambda: None)
    owner = QWidget()
    page = ToolboxPage(dependencies=ToolboxDependencies(
        rewind_service_factory=lambda: None, cultivation_service_factory=lambda: None,
        navigate_static_catalog=lambda: None, neural=neural), dialog_parent=owner)
    widget = page.build()
    widget.findChild(QPushButton, 'toolboxNeuralRendering').click()
    dialog = owner.findChild(NeuralRenderingDialog)
    assert dialog is not None
    dialog.detect.click()
    finish(app, lambda: not dialog.controller.lane.is_running())
    assert '未验证' in dialog.status.toPlainText()
    assert not mutations
    page.shutdown()
    widget.close()
    widget.deleteLater()
    owner.close()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_cancelled_plan_never_acquires_maintenance_or_writes(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    service = SimpleNamespace(prepare=lambda _: (SimpleNamespace(summary='fixture'), lambda: None),
        apply=lambda _: calls.append('apply'), close=lambda: None)
    dialog = NeuralRenderingDialog(NeuralDependencies(lambda: service, lambda: calls.append('begin'),
        lambda *_: None, lambda *_: None, lambda: None))
    monkeypatch.setattr(dialog, '_confirm', lambda *_: False)
    dialog.configure.click()
    finish(app, lambda: '已取消' in dialog.status.toPlainText())
    assert not calls
    dialog.shutdown()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

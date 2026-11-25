# 管理实验工具后台检测与提交，维护租约仅在明确写操作期间持有。
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from src.domain.localization.catalog import localized_text
from src.app.page_tasks import PageCommitLane


@dataclass(frozen=True)
class NeuralDependencies:
    service_factory: Callable
    begin: Callable
    drain: Callable
    finish: Callable
    settings: Callable
    component_directory: Path | None = None


class NeuralController(QObject):
    busy_changed = Signal(bool)
    message = Signal(str)
    prepared = Signal(object)
    directory_ready = Signal(str)

    def __init__(self, dependencies, parent):
        super().__init__(parent)
        self.dependencies = dependencies
        self.service = dependencies.service_factory()
        self.lane = PageCommitLane(self)
        self.closing = False
        self.lease = None
        self.lane.settled.connect(self._settled)

    def _submit(self, task, done):
        if self.closing or self.lane.is_running():
            return
        self.busy_changed.emit(True)
        self.lane.submit(task, lambda result: done(result) if not self.closing else None,
                         self.message.emit, self.message.emit)

    def inspect(self, folder):
        self._submit(lambda: self.service.inspect(folder), self.message.emit)

    def open_directory(self):
        self._submit(self.service.prepare_directory, self.directory_ready.emit)

    def prepare(self, folder):
        self._submit(lambda: self.service.prepare(folder), self.prepared.emit)

    def apply(self, prepared):
        self._mutate(lambda: self.service.apply(prepared), prepared[1])

    def restore(self):
        try:
            operation = self.service.prepare_restore()
            _, guard = self.service.freeze_guard()
            self._mutate(operation, guard)
        except Exception as error:
            self.message.emit(str(error))

    def _mutate(self, operation, guard):
        if self.closing or self.lane.is_running():
            return
        try:
            guard()
            self.lease = self.dependencies.begin()
        except Exception as error:
            self.message.emit(str(error))
            return
        def run():
            self.dependencies.drain(self.lease, guard)
            return operation()
        self._submit(run, self.message.emit)

    def _settled(self, success):
        if self.lease is not None:
            lease, self.lease = self.lease, None
            try:
                self.dependencies.finish(lease)
            except Exception as error:
                self.message.emit(localized_text(
                        None, 'toolbox.dlss.neural_controller.tc9e16a24',
                        '维护收尾未完成：{error}',
                        error=error,
                    ))
        self.busy_changed.emit(False)

    def close(self):
        self.closing = True
        self.service.close()

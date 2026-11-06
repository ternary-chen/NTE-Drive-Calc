# 展示全角色冻结仓库建议；采用只返回草稿，不派发游戏指令。
from copy import deepcopy
from threading import Event
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QProgressBar, QTabWidget, QVBoxLayout
from src.app.page_tasks import PageRequest, PageTaskLane
from src.app.window_geometry import fit_dialog_to_available_screen
from src.features.inventory.warehouse.recommendation_review import RecommendationReview
from src.services.inventory.warehouse_recommendation_preview import preview_targets


class RecommendationDialog(QDialog):
    def __init__(self, parent, *, build, options):
        super().__init__(parent)
        self.setWindowTitle("按已保存规则计算建议")
        self.build, self.options = build, deepcopy(options)
        self.recommendation_result = self.guard = None
        self.targets = {}
        self._cancel = Event()
        self._closing = False
        self._lane = PageTaskLane(self)
        self._lane.idle.connect(self._idle)
        layout = QVBoxLayout(self)
        self.score = QLabel()
        self.score.hide()
        layout.addWidget(self.score)
        self.tabs = QTabWidget()
        self.review = RecommendationReview(self)
        self.tabs.addTab(self.review, "建议预览")
        self.tabs.hide()
        layout.addWidget(self.tabs, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel("正在冻结输入，只读取仓库。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.generate = QPushButton("重新计算建议")
        self.generate.clicked.connect(self._start)
        self.adopt = QPushButton("采用勾选建议")
        self.adopt.setObjectName('btnNew')
        self.adopt.clicked.connect(self._adopt)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer.addWidget(self.generate)
        footer.addStretch()
        footer.addWidget(self.adopt)
        footer.addWidget(cancel)
        layout.addLayout(footer)
        for control in self.findChildren(QPushButton):
            control.ensurePolished()
            control.setMinimumHeight(control.fontMetrics().height() + 20)
            control.setMinimumWidth(control.fontMetrics().horizontalAdvance(control.text()) + 38)
        self._start()

    def is_running(self):
        return self._lane.is_running()

    def _start(self):
        if self._lane.is_running():
            return
        self._cancel = Event()
        self.recommendation_result = self.guard = None
        self.review.clear()
        self.tabs.hide()
        self.score.hide()
        self.progress.show()
        self.generate.hide()
        self.adopt.hide()
        self.adopt.setEnabled(False)
        fit_dialog_to_available_screen(self, QSize(520, 190))
        self.status.setText("正在评估全角色与全部合法蓝图，并验证弃置后的配装…")
        build, cancelled = self.build, self._cancel.is_set
        options = deepcopy(self.options)
        self._lane.submit(PageRequest(object(), lambda: build(options=options, cancel_check=cancelled),
                                     lambda value: self._receive(value, options), self._error))

    def _receive(self, value, options):
        result, guard = value
        guard.require_current()
        self.recommendation_result, self.guard, self.options = result, guard, options
        self.targets = preview_targets(result)
        self.review.set_result(result, self.targets)
        self.tabs.setCurrentWidget(self.review)
        self.tabs.show()
        self.progress.hide()
        self.generate.show()
        self.adopt.show()
        score = result.get('warehouse_score')
        self.score.setText('仓库分：暂无可评分样本' if score is None else f'仓库分：{score:.2f} / 350（本次冻结计算）')
        self.score.show()
        quality = result.get('warehouse_quality') or {}
        if quality.get('core_rate') is not None and quality.get('drive_rate') is not None:
            self.score.setToolTip(f"高分质量样本：空幕 {quality['core_rate']:.1%}（{quality['core_count']}/{quality['core_target']} 件）"
                f"；驱动 {quality['drive_rate']:.1%}（{quality['drive_count']} 件，按格数归一）。"
                f"各形状数量来自全角色去重蓝图的平均需求，汇总后四舍五入；"
                f"{sum(quality['shape_counts'][s]<n for s,n in quality['shape_targets'].items())} 种形状样本不足，按实际件数平均。"
                "这是仓库质量统计，不代表这些样本能同时给所有角色配齐。")
        fit_dialog_to_available_screen(self, QSize(1250, 760))
        counts = {state: sum(v == state for v in self.targets.values()) for state in ("locked", "discarded", "normal")}
        budget = result.get('reserve_budget') or {}
        retained = sum(self.targets.get(row['uid'], 'discarded' if row['original_discarded'] else 'normal') != 'discarded'
                       for row in result['rows'])
        budget_text = (f"\n目标保留约 {budget['target']} 件；全部采用后预计 {retained} 件不带弃置标记。"
                       if budget.get('target') else '')
        if budget.get('protected_overflow'):
            budget_text += ' 必要保护超过目标，已保留这些装备。'
        trimmed = len((result.get('diversity_budget') or {}).get('trimmed_uids', ()))
        if trimmed:
            budget_text += f'\n已压缩 {trimmed} 件相似自动保留候选；明确保留规则和各词条取向最佳件仍保留。'
        check = result.get('loss_check') or {}
        if check.get('complete'):
            restored = len(check.get('restored_uids',()))
            budget_text += f'\n全角色与已保存配装校验通过，按需补回 {restored} 件。'
            if budget.get('target') and retained > budget['target']:
                budget_text += f" 为避免已知损失及保护冲突，超过目标 {retained-budget['target']} 件。"
        self.status.setText(
            f"全部采用时待保存：锁定 {counts['locked']}、弃置 {counts['discarded']}、恢复正常 {counts['normal']}。"
            "采用后返回仓库，点击仓库“保存”才写入游戏。"
            + budget_text
            + ('\n' + '\n'.join(result['limitations']) if result.get('limitations') else '')
        )
        self.adopt.setEnabled(not self._lane.is_running())

    def _adopt(self):
        try:
            self.guard.require_current()
        except Exception as exc:
            self._error(str(exc))
            return
        try:
            self.guard.require_targets(self.review.checked_targets())
        except ValueError as exc:
            self.status.setText(str(exc))
            return  # 勾选不完整仍可原地修正，不丢弃已经冻结并验证的结果。
        self.targets = self.review.checked_targets()
        self.accept()

    def _error(self, message):
        self.recommendation_result = self.guard = None
        self.progress.hide()
        self.generate.show()
        self.adopt.setEnabled(False)
        self.status.setText(message)

    def _idle(self):
        if self._closing:
            super().reject()
            return
        self.adopt.setEnabled(self.guard is not None)
        self.generate.setEnabled(True)

    def reject(self):
        self._cancel.set()
        if self._lane.is_running():
            self._closing = True
            self._lane.cancel()
            self.status.setText("正在取消，等待本次计算释放资源…")
        else:
            super().reject()

    def closeEvent(self, event):
        if self._lane.is_running():
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)

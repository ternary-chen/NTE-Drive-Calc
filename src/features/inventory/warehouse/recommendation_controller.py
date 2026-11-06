# 将推荐弹窗接入仓库草稿，账号代次和冻结输入通过现有保存流程再次核对。
from __future__ import annotations

from copy import deepcopy
from functools import partial

from PySide6.QtWidgets import QDialog, QMessageBox

from src.app.context import CallbackAccountLifecycle
from src.features.inventory.warehouse.cards import warehouse_item_with_state
from src.features.inventory.warehouse.recommendation_dialog import RecommendationDialog
from src.services.identification.matching_settings import MatchingSettingsService
from src.services.inventory.warehouse_recommendation_preview import build_preview
from src.services.inventory.warehouse_rule_generation import generate_warehouse_rules
from src.domain.equipment.intelligent_rules import remembered_drive_grade


class WarehouseRecommendationFlow:
    def __init__(self, context):
        self.context = context
        self.identity = (context.account.active_account_id, context.generation)
        self.database = context.account.user_database_path
        self.preview = None

    def check_context(self):
        if (self.context.account.active_account_id, self.context.generation) != self.identity:
            raise ValueError("账号已切换，请在当前账号重新生成建议")

    def open(self, editor, config, matching, *, mode="rules"):
        self.preview = None
        self.check_context()
        if mode == 'rules':
            choice = remembered_drive_grade(config)
            if choice is None:
                return self._generate_first(editor, config, matching)
            generated = generate_warehouse_rules(self.context.paths.equipment_allocation_database_path,
                                                 config['preserve_rules'],grade_choice=choice)
            self.check_context()
            return generated
        matching = deepcopy(matching if matching is not None else MatchingSettingsService(self.database).load())
        build = partial(
            build_preview,
            database=self.database,
            static_database=self.context.paths.equipment_allocation_database_path,
            asset_root=self.context.paths.equipment_allocation_asset_root,
            config_dir=self.context.paths.config_dir,
            config=deepcopy(config),
            matching=matching,
            check_context=self.check_context,
        )
        dialog = RecommendationDialog(editor, build=build, options=config.get("recommendation", {}))
        unregister = self.context.register_account_lifecycle(
            CallbackAccountLifecycle(
                is_running=dialog.is_running, stop=dialog.reject, rebuild=lambda _: None, start=lambda: None
            )
        )
        try:
            if dialog.exec() != QDialog.Accepted:
                return None
            saved_config = deepcopy(config)
            saved_config["recommendation"] = deepcopy(dialog.options)
            self.preview = (dialog.recommendation_result, dialog.guard, dict(dialog.targets), saved_config, matching)
            return dialog.options
        finally:
            unregister()
            dialog.deleteLater()

    def _generate_first(self, editor, config, matching):
        from src.features.inventory.warehouse.rule_generation_progress import RuleGenerationProgress
        from src.services.inventory.warehouse_quality_assessment import generate_first_rules
        pinned_matching = deepcopy(matching if matching is not None else MatchingSettingsService(self.database).load())
        dialog = RuleGenerationProgress(editor, build=partial(generate_first_rules,
            database=self.database, static_database=self.context.paths.equipment_allocation_database_path,
            config_dir=self.context.paths.config_dir, config=deepcopy(config), matching=pinned_matching,
            check_context=self.check_context))
        unregister = self.context.register_account_lifecycle(CallbackAccountLifecycle(
            is_running=dialog.is_running,stop=dialog.reject,rebuild=lambda _:None,start=lambda:None))
        try:
            if dialog.exec()!=QDialog.Accepted:
                return None
            self.check_context()
            return dialog.generated
        finally:
            unregister()
            dialog.deleteLater()

    def calculate_saved(self, parent, config):
        return self.open(parent, config, None, mode='preview')

    @staticmethod
    def pending_without_recommendation(host):
        pending = dict(host._warehouse_pending_state_changes)
        for uid, state in host.warehouse_read_controller.recommendation_targets.items():
            if pending.get(uid) == state:
                pending.pop(uid)
        return pending

    @staticmethod
    def invalidate_staged(host):
        owner = host.warehouse_read_controller
        if owner.recommendation_guard is None:
            return
        try:
            owner.recommendation_guard.require_current()
            return
        except ValueError:
            pass
        tracked = set(owner.recommendation_targets)
        pending = WarehouseRecommendationFlow.pending_without_recommendation(host)
        host._warehouse_pending_state_changes = pending
        host._warehouse_all_items = [warehouse_item_with_state(item, pending.get(str(item['uid']),
            host._warehouse_base_states[str(item['uid'])])) if str(item['uid']) in tracked else item
            for item in host._warehouse_all_items]
        owner.recommendation_targets = {}
        owner.recommendation_guard = None
        owner.score_label.setText('仓库分：规则或输入已变化，请重新计算建议')
        host._apply_warehouse_filters()
        host._update_warehouse_save_state()

    def stage(self, host):
        if self.preview is None:
            return False
        result, guard, targets, config, matching = self.preview
        try:
            guard.bind_saved_settings(config, matching)
            if host._warehouse_snapshot_id != guard.snapshot_id:
                raise ValueError("仓库页面与推荐快照不同，请刷新后重试")
            pending = self.pending_without_recommendation(host)
            conflicts = set(pending).intersection(targets)
            if any(pending[uid] != targets[uid] for uid in conflicts):
                raise ValueError("已有手动修改与推荐冲突，请先保存或撤销手动修改")
            generated_targets = {uid: state for uid, state in targets.items() if uid not in pending}
            pending.update(targets)
            guard.require_targets(pending)
            host._warehouse_pending_state_changes = pending
            tracked = set(host.warehouse_read_controller.recommendation_targets)
            host._warehouse_all_items = [warehouse_item_with_state(item, pending.get(str(item['uid']),
                host._warehouse_base_states[str(item['uid'])]))
                if str(item['uid']) in pending or str(item['uid']) in tracked else item
                for item in host._warehouse_all_items]
            owner = host.warehouse_read_controller
            owner.cancel_quality()
            owner.recommendation_guard = guard
            # 相同目标也不能把用户的手动草稿转为智能建议，后续失效只撤销本轮新增目标。
            owner.recommendation_targets = generated_targets
            score = result["warehouse_score"]
            owner.score_label.setText(
                "仓库分：暂无可评分样本" if score is None else f"仓库分：{score:.2f} / 350（本次推荐）"
            )
            host._apply_warehouse_filters()
            host._update_warehouse_save_state()
        except Exception as exc:
            QMessageBox.warning(host, "建议未采用", str(exc))
        return True

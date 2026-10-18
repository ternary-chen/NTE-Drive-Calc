# 使用队伍名和四人头像卡片选择战报增强目标，每队独立选择战报及半场。
from datetime import datetime
from concurrent.futures import CancelledError

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from src.app.theme import themed_style
from src.app.window_geometry import fit_dialog_to_available_screen
from src.domain.teams import TeamRole
from src.features.teams.cards import MemberSlots, set_role
from src.integrations.bundled_resources import bundled_game_ui_asset_root
from src.integrations.game_assets.catalog import GameUiAssetCatalog
from src.services.allocation.team_axis_selection import select_team_axes
from src.ui.widgets import NoWheelComboBox


def report_label(entry, names):
    try:
        saved = datetime.fromisoformat(entry.saved_at_utc.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        saved = entry.saved_at_utc
    scene = entry.environment_name or (f"深渊 {entry.abyss_floor} 层" if entry.abyss_floor else "场景未记录")
    members = "／".join(names.get(key, str(key)) for key in entry.character_ids)
    return f"#{entry.battle_record_id} · {scene} · 整份记录 {entry.duration_seconds:.0f} 秒 · {saved} · {members}"


class TeamAxisDialog(QDialog):
    def __init__(self, *, service, teams, choices, initial=None, initial_request=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("战报增强 · 选择队伍")
        self.selection = None
        self._service, self._choices = service, choices
        self._rows = []
        names = {key: name for name, key in choices.role_character_ids}
        assets = GameUiAssetCatalog(bundled_game_ui_asset_root())
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        hint = QLabel("最多选择两支角色不重复的队伍，每队选择一份对应战报。\n先按队内伤害名次分配当前背包：两队同名次并列，再优化综合增幅；其余角色按原策略分配。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        cards = QVBoxLayout(content)
        cards.setAlignment(Qt.AlignTop)
        if not teams:
            cards.addWidget(QLabel("还没有队伍，请先到侧栏「队伍」新建并配置四名成员。"))
        for team in teams:
            card = QWidget()
            card.setObjectName("axisTeamCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            check = QCheckBox(team.name)
            check.setAccessibleName(f"选择队伍 {team.name}")
            layout.addWidget(check)
            slots = MemberSlots(card)
            for index, button in enumerate(slots.buttons):
                if index < len(team.character_ids):
                    key = team.character_ids[index]
                    set_role(button, TeamRole(key, names.get(key, f"角色 {key}"), str(assets.character_icon(key) or "")))
                button.clicked.connect(check.toggle)
            layout.addWidget(slots)
            reason = QLabel()
            reason.setWordWrap(True)
            layout.addWidget(reason)
            config = QWidget()
            form = QFormLayout(config)
            report = NoWheelComboBox()
            report.setSizeAdjustPolicy(NoWheelComboBox.AdjustToMinimumContentsLengthWithIcon)
            report.setMinimumContentsLength(20)
            report.addItem("请选择对应战报", None)
            report.setAccessibleName(f"{team.name}的参考战报")
            for entry in choices.entries:
                # 摘要仅帮助挑选；正式四人匹配仍由计算前的原生队伍证据校验。
                report.addItem(report_label(entry, names), entry.battle_record_id)
                report.setItemData(report.count() - 1, report.itemText(report.count() - 1), Qt.ToolTipRole)
            scope = NoWheelComboBox()
            scope.setAccessibleName(f"{team.name}的战报范围")
            anchor = NoWheelComboBox()
            anchor.setAccessibleName(f"{team.name}的战报配置")
            form.addRow("参考战报", report)
            form.addRow("使用范围", scope)
            form.addRow("角色养成", anchor)
            time_widget = QWidget()
            time_layout = QHBoxLayout(time_widget)
            time_layout.setContentsMargins(0, 0, 0, 0)
            start, end = QDoubleSpinBox(), QDoubleSpinBox()
            for control, name in ((start, "开始秒"), (end, "结束秒")):
                control.setRange(0, 86400)
                control.setDecimals(6)
                control.setSuffix(" 秒")
                control.setAccessibleName(team.name + name)
                time_layout.addWidget(control)
            time_label = QLabel("指定时段")
            form.addRow(time_label, time_widget)
            layout.addWidget(config)
            row = dict(team=team, card=card, check=check, config=config, reason=reason,
                       report=report, scope=scope, anchor=anchor, slots=slots,
                       start=start, end=end, time=time_widget, time_label=time_label)
            self._rows.append(row)
            report.currentIndexChanged.connect(lambda _index, current=row: self._report_changed(current))
            scope.currentIndexChanged.connect(lambda _index, current=row: self._scope_changed(current))
            check.toggled.connect(self._update_selection)
            self._report_changed(row)
            cards.addWidget(card)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setTextFormat(Qt.PlainText)
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        self.buttons = buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("应用战报增强")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._update_selection()
        if initial is not None:
            for row in self._rows:
                binding = next((b for b in initial.teams if b.team.team_id == row["team"].team_id), None)
                if binding:
                    row["check"].setChecked(True)
                    row["report"].setCurrentIndex(row["report"].findData(binding.axis.battle.battle_record_id))
                    row["scope"].setCurrentIndex(row["scope"].findData("range" if binding.axis.battle.start_us is not None else binding.axis.battle.detail_scope or "all"))
                    row["start"].setValue((binding.axis.battle.start_us or 0) / 1_000_000)
                    row["end"].setValue((binding.axis.battle.end_us or 0) / 1_000_000)
                    row["anchor"].setCurrentIndex(row["anchor"].findData(binding.axis.anchor_mode))
        elif initial_request is not None:
            for row in self._rows:
                row["report"].setCurrentIndex(row["report"].findData(initial_request.battle_record_id))
                row["scope"].setCurrentIndex(row["scope"].findData("range" if initial_request.start_us is not None else initial_request.detail_scope or "all"))
                row["start"].setValue((initial_request.start_us or 0) / 1_000_000)
                row["end"].setValue((initial_request.end_us or 0) / 1_000_000)
        fit_dialog_to_available_screen(self, QSize(940, 720))

    def _report_changed(self, row):
        record_id = row["report"].currentData()
        entry = next((e for e in self._choices.entries if e.battle_record_id == record_id), None)
        scope, anchor = row["scope"], row["anchor"]
        scope.clear()
        anchor.clear()
        if entry is None:
            scope.addItem("先选择战报", None)
            return
        if entry.has_first_half and entry.has_second_half:
            scope.addItem("请选择对应队伍的半场", None)
        else:
            scope.addItem("整份战报", "all")
        if entry.has_first_half:
            scope.addItem("上半场", "first")
        if entry.has_second_half:
            scope.addItem("下半场", "second")
        scope.addItem("指定时段", "range")
        anchor.addItem("战报原始配置", "original")
        if record_id in self._choices.active_edit_record_ids:
            anchor.addItem("已启用的编辑配置", "effective")

    def _scope_changed(self, row):
        visible = row["scope"].currentData() == "range"
        row["time"].setVisible(visible)
        row["time_label"].setVisible(visible)

    def _update_selection(self):
        chosen = [row for row in self._rows if row["check"].isChecked()]
        used = {key for row in chosen for key in row["team"].character_ids}
        names = {key: name for name, key in self._choices.role_character_ids}
        for row in self._rows:
            selected = row["check"].isChecked()
            team = row["team"]
            conflicts = used.intersection(team.character_ids) if not selected else set()
            reason = ("请先在队伍菜单补齐四名成员" if len(team.character_ids) != 4 else
                      "重复成员：" + "、".join(names.get(key, str(key)) for key in sorted(conflicts)) if conflicts else
                      "最多选择两支队伍" if not selected and len(chosen) >= 2 else "")
            row["check"].setEnabled(selected or not reason)
            for button in row["slots"].buttons:
                button.setEnabled(selected or not reason)
            row["reason"].setText(reason)
            row["reason"].setVisible(bool(reason))
            row["config"].setVisible(selected)
            color = "#58a6ff" if selected else "#30363d"
            row["card"].setStyleSheet(themed_style(
                f"QWidget#axisTeamCard{{border:1px solid {color};border-radius:8px;background:#0d1117;}}"))

    def _accept(self):
        try:
            self.selection = select_team_axes(self._service, self._choices, [
                (row["team"], row["report"].currentData(), row["scope"].currentData(), row["anchor"].currentData(),
                 round(row["start"].value() * 1_000_000), round(row["end"].value() * 1_000_000))
                for row in self._rows if row["check"].isChecked()])
        except CancelledError:
            self.reject()
            return
        except (ValueError, RuntimeError) as error:
            self.error.setText(str(error))
            return
        self.accept()

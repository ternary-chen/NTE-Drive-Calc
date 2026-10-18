# 计算页独立战报增强入口，不修改原角色顺序和属性权重。
from concurrent.futures import CancelledError

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton
from PySide6.QtCore import Qt

from src.features.allocation.team_axis_dialog import TeamAxisDialog
from src.services.allocation.team_axis_selection import load_team_choices
from src.services.allocation.search_settings import SEARCH_MODES, load_search_mode, save_search_mode


def build_team_axis_controls(owner, header, layout):
    owner.team_axis_selection = None
    owner.team_axis_check = QCheckBox("战报增强")
    owner.team_axis_check.setToolTip("先优化一支或两支互斥队伍，其余角色继续按原策略分配")
    owner.team_axis_configure = QPushButton("配置队伍与战报")
    owner.team_axis_configure.setObjectName("btnAction")
    header.addSpacing(16)
    header.addWidget(owner.team_axis_check)
    header.addSpacing(8)
    header.addWidget(owner.team_axis_configure)
    search_row = QHBoxLayout()
    search_row.addWidget(QLabel("战报增强搜索"))
    owner.team_axis_search = QComboBox()
    owner.team_axis_search.setAccessibleName("战报增强搜索档位")
    for key, label in SEARCH_MODES:
        owner.team_axis_search.addItem(label, key)
    owner.team_axis_search.setToolTip("快搜适合日常预览；深搜检查更多组合。两档公式相同，实际耗时取决于战报和电脑性能，可随时取消。")
    reload_search_mode(owner)
    search_row.addWidget(owner.team_axis_search)
    search_row.addStretch(1)
    layout.addLayout(search_row)
    owner.team_axis_search.currentIndexChanged.connect(lambda: persist_search_mode(owner))
    owner.team_axis_summary = QLabel()
    owner.team_axis_summary.setTextFormat(Qt.PlainText)
    owner.team_axis_summary.setWordWrap(True)
    layout.addWidget(owner.team_axis_summary)
    owner.team_axis_summary.hide()
    owner.team_axis_configure.clicked.connect(lambda: configure_team_axes(owner))

    def toggled(enabled):
        if enabled and owner.team_axis_selection is None:
            configure_team_axes(owner)
            if owner.team_axis_selection is None:
                owner.team_axis_check.setChecked(False)
        owner.team_axis_summary.setVisible(owner.team_axis_check.isChecked())

    owner.team_axis_check.toggled.connect(toggled)


def reload_search_mode(owner):
    combo = getattr(owner, "team_axis_search", None)
    if combo is None:
        return
    mode = load_search_mode(owner.app_context.account.user_database_path)
    previous = combo.blockSignals(True)
    combo.setCurrentIndex(combo.findData(mode))
    combo.blockSignals(previous)


def persist_search_mode(owner):
    try:
        save_search_mode(owner.app_context.account.user_database_path, owner.team_axis_search.currentData())
    except Exception as error:
        reload_search_mode(owner)
        QMessageBox.warning(owner.dialog_parent, "保存搜索档位失败", str(error))


def configure_team_axes(owner, *, initial_request=None):
    provider = owner._axis_selection_service_provider
    if provider is None:
        return None
    try:
        service = provider()
        teams, choices = load_team_choices(service, tuple(owner.role_selector.all_roles))
        dialog = TeamAxisDialog(service=service, teams=teams, choices=choices,
                                initial=owner.team_axis_selection, initial_request=initial_request,
                                parent=owner.dialog_parent)
    except CancelledError:
        return None
    except (ValueError, RuntimeError) as error:
        QMessageBox.warning(owner.dialog_parent, "战报增强", str(error))
        return None
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        owner.team_axis_selection = dialog.selection
        lines = [f"{binding.team.name}：{'、'.join(binding.roles)} · 战报 #{binding.axis.battle.battle_record_id}"
                 for binding in dialog.selection.teams]
        owner.team_axis_summary.setText("\n".join(lines) + "\n所选队伍按队内伤害名次先分配，同名次并列，再优化增幅；其余角色使用剩余装备。")
        owner.team_axis_check.setChecked(True)
        owner.team_axis_summary.show()
        return dialog.selection
    finally:
        dialog.close()
        dialog.deleteLater()

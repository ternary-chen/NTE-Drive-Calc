# 展示本账号独立队伍列表，成员选择与重命名共用编辑弹窗。
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from src.app.theme import themed_style
from src.domain.name_search import match_pinyin
from src.domain.teams import TeamRole
from src.features.teams.cards import MemberSlots, set_role


class TeamPage(QWidget):
    create_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._teams = ()
        self._roles = {}
        self._cards = []
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel("我的队伍")
        title.setStyleSheet("font-size:20px;font-weight:700")
        header.addWidget(title)
        header.addStretch()
        create = QPushButton("＋ 新建队伍")
        create.setObjectName("btnAction")
        create.clicked.connect(self.create_requested.emit)
        header.addWidget(create)
        root.addLayout(header)
        hint = QLabel("每支队伍最多四人，可保存多个备用阵容。同一角色可以加入不同队伍。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索队伍名称或成员（支持拼音）…")
        self.search.setAccessibleName("搜索队伍")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.cards_layout = QVBoxLayout(self.content)
        self.cards_layout.setContentsMargins(0, 0, 8, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch()
        scroll.setWidget(self.content)
        root.addWidget(scroll, 1)
        self.empty = QLabel("还没有队伍，点击右上角「新建队伍」开始配置。")
        self.empty.setWordWrap(True)
        self.cards_layout.insertWidget(0, self.empty)

    def clear_account(self):
        self.search.clear()
        self.show_teams((), ())
        self.status.clear()

    def show_teams(self, teams, roles):
        self._teams = tuple(teams)
        self._roles = {role.character_id: role for role in roles}
        for widget, _ in self._cards:
            self.cards_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._cards.clear()
        for team in teams:
            card = QWidget()
            card.setObjectName("teamCard")
            card.setStyleSheet(themed_style(
                "QWidget#teamCard{background:#0d1117;border:1px solid #30363d;border-radius:10px;}"))
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 12, 16, 14)
            heading = QHBoxLayout()
            name = QLabel(team.name)
            name.setTextFormat(Qt.PlainText)
            name.setWordWrap(True)
            name.setStyleSheet("font-size:15px;font-weight:700")
            heading.addWidget(name, 1)
            count = len(team.character_ids)
            heading.addWidget(QLabel(f"{count}/4" + (" · 待补齐" if count < 4 else " · 已满员")))
            edit = QPushButton("编辑")
            edit.setAccessibleName(f"编辑队伍 {team.name}")
            edit.clicked.connect(lambda checked=False, key=team.team_id: self.edit_requested.emit(key))
            heading.addWidget(edit)
            delete = QPushButton("删除")
            delete.setAccessibleName(f"删除队伍 {team.name}")
            delete.clicked.connect(lambda checked=False, key=team.team_id: self.delete_requested.emit(key))
            heading.addWidget(delete)
            layout.addLayout(heading)
            members = MemberSlots(card)
            names = [team.name]
            for index in range(4):
                role = None
                if index < count:
                    key = team.character_ids[index]
                    role = self._roles.get(key, TeamRole(key, f"角色 {key}（暂不可用）"))
                    names.append(role.name)
                button = members.buttons[index]
                set_role(button, role)
                button.setAccessibleName(f"编辑队伍 {team.name}，" + (role.name if role else "添加成员"))
                button.clicked.connect(lambda checked=False, key=team.team_id: self.edit_requested.emit(key))
            layout.addWidget(members)
            self._cards.append((card, names))
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.status.setText(f"已保存 {len(teams)} 支队伍")
        self._filter()

    def _filter(self):
        query = self.search.text().strip()
        count = 0
        for card, names in self._cards:
            visible = not query or any(match_pinyin(name, query) for name in names)
            card.setVisible(visible)
            count += int(visible)
        self.empty.setVisible(count == 0)
        self.empty.setText("没有匹配的队伍" if self._teams else "还没有队伍，点击右上角「新建队伍」开始配置。")

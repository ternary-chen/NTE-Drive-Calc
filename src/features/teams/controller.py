# 持有队伍页和当前编辑弹窗；账号切换撤销旧草稿，失败保留可重试编辑内容。
import sqlite3

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from src.features.teams.editor import TeamEditor
from src.features.teams.page import TeamPage
from src.services.teams import TeamSessionExpired


class TeamController(QObject):
    def __init__(self, *, service_provider, parent=None):
        super().__init__(parent)
        self._service_provider = service_provider
        self.page = TeamPage(parent)
        self._teams = {}
        self._dialog = None
        self.page.create_requested.connect(self.create)
        self.page.edit_requested.connect(self.edit)
        self.page.delete_requested.connect(self.delete)

    def refresh(self):
        try:
            service = self._service_provider()
            teams = service.list_teams()
            try:
                roles = service.roles()
                warning = ""
            except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
                roles, warning = (), f"角色资料暂不可用：{error}。已保存队伍仍保留。"
            service.checkpoint()
            self._teams = {team.team_id: team for team in teams}
            self.page.show_teams(teams, roles)
            if warning:
                self.page.status.setText(warning)
            return not warning
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            self.page.status.setText(f"已保存队伍加载失败：{error}")
            return False

    def create(self):
        self._edit(None)

    def edit(self, team_id):
        team = self._teams.get(team_id)
        if team is not None:
            self._edit(team)

    def _edit(self, team):
        if self._dialog is not None:
            self._dialog.raise_()
            return
        service = self._service_provider()
        try:
            roles = service.roles()
            dialog = TeamEditor(roles=roles, team=team, parent=self.page)
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            self.page.status.setText(f"暂时无法编辑队伍：{error}")
            return
        self._dialog = dialog

        def save():
            try:
                service.save(dialog.draft(), existing=team)
            except TeamSessionExpired:
                dialog.reject()
                return
            except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
                dialog.error.setText(f"未保存：{error}")
                return
            dialog.accept()
            if self.refresh():
                self.page.status.setText("队伍已保存")

        def finished(_result):
            self._dialog = None
            dialog.deleteLater()

        dialog.save_requested.connect(save)
        dialog.finished.connect(finished)
        dialog.open()

    def delete(self, team_id):
        team = self._teams.get(team_id)
        if team is None:
            return
        service = self._service_provider()
        box = QMessageBox(QMessageBox.Warning, "删除队伍", f"删除队伍“{team.name}”？\n角色、配装和战报不会被删除。",
                          QMessageBox.Yes | QMessageBox.Cancel, self.page)
        box.setTextFormat(Qt.PlainText)
        box.button(QMessageBox.Yes).setText("删除队伍")
        box.button(QMessageBox.Cancel).setText("取消")
        box.setDefaultButton(QMessageBox.Cancel)
        QApplication.beep()
        result = box.exec()
        box.deleteLater()
        if result != QMessageBox.Yes:
            return
        try:
            service.delete(team)
            if self.refresh():
                self.page.status.setText("队伍已删除")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
            self.page.status.setText(f"未删除：{error}")

    def reset_account(self):
        if self._dialog is not None:
            self._dialog.reject()
        self._teams.clear()
        self.page.clear_account()

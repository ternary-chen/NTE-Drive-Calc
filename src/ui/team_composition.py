# 在组合根冻结队伍服务的账号路径与代次，并注册页面草稿的账号切换生命周期。
from src.app.context import CallbackAccountLifecycle
from src.features.teams.controller import TeamController
from src.services.teams import TeamService


def build_team_controller(app_context, parent):
    def service_provider():
        account = app_context.account
        generation = app_context.generation
        return TeamService(
            account_id=account.active_account_id, database_path=account.user_database_path,
            static_database_path=app_context.paths.cultivation_database_path,
            asset_root=app_context.paths.game_ui_asset_root,
            context_is_current=lambda: app_context.generation == generation and app_context.account == account,
        )

    controller = TeamController(service_provider=service_provider, parent=parent)
    unregister = app_context.register_account_lifecycle(CallbackAccountLifecycle(
        is_running=lambda: False, stop=controller.reset_account,
        rebuild=lambda account: controller.reset_account(), start=lambda: None,
    ))
    controller.destroyed.connect(lambda: unregister())
    return controller

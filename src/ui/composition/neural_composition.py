# 组合实验工具的模式门禁、原生维护租约与部署记录，不向功能页暴露主窗口。
from pathlib import Path

from src.features.toolbox.neural_controller import NeuralDependencies
from src.integrations.components.inspection import inspect_deployed_native_plugin
from src.integrations.components.native_files import NativePluginDeployment
from src.integrations.components.reshade_chain import CHAIN_HOST
from src.services.components.neural_rendering import NeuralRenderingService


def build_neural_dependencies(window):
    context = window.app_context
    policy = window.work_mode_service
    session = window.native_game_session

    def guard(capability):
        window.operation_guard(capability)
        if policy.settings.paused:
            raise PermissionError('当前已安全暂停，请先确认工作模式与环境。')
        if policy.settings.pending_cleanup:
            raise RuntimeError('Calc 组件仍待清理，请先到环境设置完成处理。')
        if policy.deployment_record.get('loading_method') == 'loader':
            raise RuntimeError('此实验使用 D3D 代理，请先在环境设置切换加载方式。')
        if window._mod_plugin_loading_service.snapshot().phase == 'running':
            raise RuntimeError('请先停止独立 Loader，再配置代理串联。')

    def begin():
        guard('native_load')
        if window.work_mode_controller.is_transitioning or window.global_hotkey_manager.active_owner is not None:
            raise RuntimeError('模式或游戏操作尚未收尾，请稍后配置。')
        lease = session.reserve_plugin_maintenance()
        try:
            window.auto_sync_controller.suspend_for_plugin_update()
            window.performance_controller.suspend_for_plugin_update()
        except Exception:
            lease.close()
            window.auto_sync_controller.resume_after_plugin_update(restore=False)
            window.performance_controller.resume_after_plugin_update(restore=False)
            raise
        return lease, window.operation_generation()

    def drain(owner, check):
        check()
        if not window.performance_controller.wait_plugin_update_idle():
            raise RuntimeError('性能采样尚未完成收尾，请稍后再试。')
        owner[0].disconnect(check=check)

    def finish(owner):
        restore = owner[1] == window.operation_generation()
        try:
            if restore:
                executable = Path(policy.settings.game_executable)
                inspection = inspect_deployed_native_plugin(application_root=context.paths.root,
                    game_executable_path=executable)
                if inspection.files_compatible:
                    files = {name: item.sha256 for name, item in inspection.files.items()}
                    host = CHAIN_HOST if CHAIN_HOST in files else 'd3d12.dll'
                    window.work_mode_runtime.save_deployment(NativePluginDeployment(
                        executable, executable.parent / host, files[host], executable.parent,
                        None, files, deployment_layout=inspection.layout))
        finally:
            owner[0].close()
            window.auto_sync_controller.resume_after_plugin_update(restore=restore)
            window.performance_controller.resume_after_plugin_update(restore=restore)
            window.work_mode_runtime.invalidate()

    return NeuralDependencies(
        service_factory=lambda: NeuralRenderingService(root=context.paths.root, config=context.paths.config_dir,
            game_path=lambda: policy.settings.game_executable, guard=guard, generation=window.operation_generation,
            component_directory=context.paths.data_root / 'user-components/neural-rendering'),
        begin=begin, drain=drain, finish=finish, settings=lambda: window._go('settings'),
        component_directory=context.paths.data_root / 'user-components/neural-rendering',
    )

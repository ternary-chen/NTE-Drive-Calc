# 冻结实验图形配置请求并编排文件事务，不读写账号数据库。
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from src.domain.localization.catalog import localized_text
from src.integrations.components.neural_profile import inspect_source, plan_install, targets
from src.integrations.components.neural_transaction import FileTransaction, checked_path
from src.integrations.components.environment import game_process_running


class NeuralRenderingService:
    def __init__(self, *, root: Path, config: Path, game_path, guard, generation,
                 game_running=game_process_running, component_directory=None):
        self.root, self.config = root, config
        self.game_path, self.guard, self.generation = game_path, guard, generation
        self.game_running = game_running
        self.closed = False
        self.component_directory = component_directory or config.parent / 'user-components/neural-rendering'

    def prepare_directory(self):
        checked_path(self.component_directory / '.directory-check')
        self.component_directory.mkdir(parents=True, exist_ok=True)
        return str(self.component_directory)

    def close(self):
        self.closed = True

    def _transaction(self, executable):
        key = hashlib.sha256(str(executable).casefold().encode('utf-8')).hexdigest()[:24]
        return FileTransaction(self.config / 'neural-rendering' / key, targets(executable))

    def inspect(self, folder: str) -> str:
        executable = Path(self.game_path()).absolute()
        tx = self._transaction(executable)
        status = {'absent': '尚未配置', 'configured': '已配置，需进入游戏实测',
                  'changed': '配置后文件有变化，请检查或恢复', 'pending': '上次未完成，可恢复本次配置',
                  'restored': '本次修改已恢复'}[tx.status()]
        components = '\n'.join(inspect_source(Path(folder).absolute())) if folder else '请选择包含三个组件的目录。'
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total',
                '--format=csv,noheader'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            gpu = result.stdout.strip() if result.returncode == 0 else '显卡检测未完成'
        except (OSError, subprocess.SubprocessError):
            gpu = '显卡检测未完成'
        running = self.game_running()
        game = '游戏运行中，请先退出' if running else ('游戏已退出' if running is False else '游戏状态未确认')
        return localized_text(
                   None, 'toolbox.dlss.neural_rendering.t5cf8c39d',
                   '{status}\n{game}\n{gpu}\n\n{components}\n\n驱动兼容性、DLSS 5 效果和 Calc 共存仍待实测。',
                   status=status, game=game, gpu=gpu, components=components or '三个组件与候选哈希一致。',
               )

    def freeze_guard(self):
        generation, game = self.generation(), self.game_path()
        def check():
            if self.closed:
                raise RuntimeError('工具已关闭，操作停止；已写文件可从恢复入口处理。')
            self.guard('native_load')
            if self.generation() != generation or self.game_path() != game:
                raise RuntimeError('账号、模式或游戏路径已改变，请重新操作。')
            if self.game_running() is not False:
                raise RuntimeError('必须确认游戏已退出后才能配置或恢复。')
        check()
        return Path(game).absolute(), check

    def prepare(self, folder):
        executable, guard = self.freeze_guard()
        tx = self._transaction(executable)
        if tx.status() not in {'absent', 'restored'}:
            raise RuntimeError('已有实验配置，请先检查或恢复；不重复叠加安装。')
        plan = plan_install(self.root, executable, Path(folder).absolute())
        guard()
        return plan, guard

    def apply(self, prepared):
        plan, guard = prepared
        try:
            self._transaction(plan.executable).apply(plan.changes, guard)
        except Exception as error:
            raise RuntimeError(localized_text(
                    None, 'toolbox.dlss.neural_rendering.tea540720',
                    '配置未完成：{error}\n若已有写入，请保持游戏关闭并使用“恢复本次配置”。',
                    error=error,
                )) from error
        return '组件已配置。重启游戏，在 ReShade 的 Add-ons 中开启神经渲染，再验证同步、战报和 HUD。'

    def prepare_restore(self):
        executable, guard = self.freeze_guard()
        return lambda: self._restore(executable, guard)

    def _restore(self, executable, guard):
        self._transaction(executable).restore(guard)
        return '本次配置已恢复；玩家新增的 ReShade 偏好会保留。重启游戏后复核 Calc。'

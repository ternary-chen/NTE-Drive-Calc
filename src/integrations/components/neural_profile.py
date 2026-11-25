# 冻结本轮已核对的实验组件身份和作者入口，不包含第三方二进制。
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import zipfile

from src.domain.localization.catalog import localized_text
from src.integrations.components.neural_transaction import Change, checked_path, file_hash
from src.integrations.components.inspection import inspect_deployed_native_plugin
from src.integrations.components.reshade_chain import CHAIN_HOST, configured_bytes, configuration_values
from src.integrations.components.native_plugin_bundle import HOT_PLUGIN_LAYOUTS, inspect_native_plugin_bundle

SOURCES = (
    ('ReShade Add-on 官网', 'https://reshade.me/'),
    ('RenoDX 作者下载频道', 'https://discord.com/channels/1408098019194310818/1545049227321810974'),
)
PROFILE_LABEL = '指定实验方案：ReShade 6.8.0 · ShortFuse 2026-10-17 · NR 310.9.16'
COMPONENTS = (
    ('ReShade64.dll', '6.8.0.2155', '0cee63f9c9f13f3ac909c5b4903f4dbb4b719a7ab3b4f13b0deaf83c814b94f7'),
    ('renodx-dlss.addon64', '0.2026.1016.1704', 'a8fd34b531fd22c3dbd008ed8fd3cbfcca2fb451729e19cd1fc2e4c85b5068d4'),
    ('nvngx_dlssnr.dll', '310.9.16.0', '2bc19bc09a7b89dd44f73e2ac0108fcc586e2154bdd0830f242f4f040e28789f'),
)
ARCHIVES = {
    'ReShade64.dll': ('ReShade_Setup_6.8.0_Addon.exe',
        'afe4c8f13048306307983b8b3d41d5bf00a86820440b0e57dea10950e1176445'),
    'nvngx_dlssnr.dll': ('nvngx_dlssnr_2026_10_16.zip',
        '764f94a32ec302b9fe4da9a1246fd7dd9176e490d8766667687c9fd89da2ab12'),
}


def component_bytes(folder: Path, name: str) -> bytes:
    direct = checked_path(folder / name)
    if direct.is_file():
        if direct.stat().st_size > 512 * 1024 * 1024:
            raise RuntimeError(localized_text(
                    None, 'toolbox.dlss.neural_profile.tcf861a73',
                    '{name} 超出候选大小限制。',
                    name=name,
                ))
        return direct.read_bytes()
    if name in ARCHIVES:
        filename, digest = ARCHIVES[name]
        archive = checked_path(folder / filename)
        if archive.is_file():
            if file_hash(archive) != digest:
                raise RuntimeError(localized_text(
                        None, 'toolbox.dlss.neural_profile.td7395968',
                        '{filename} 与本轮已核对下载包不同。',
                        filename=filename,
                    ))
            # 仅解读已确认包内的确切成员，不运行安装器、不展开其他路径。
            with zipfile.ZipFile(archive) as source:
                members = [entry for entry in source.infolist() if entry.filename == name]
                if len(members) != 1 or members[0].file_size > 512 * 1024 * 1024:
                    raise RuntimeError(localized_text(
                            None, 'toolbox.dlss.neural_profile.td24d9cb1',
                            '{filename} 内的组件成员不明确。',
                            filename=filename,
                        ))
                return source.read(members[0])
    raise FileNotFoundError(name)


def inspect_source(folder: Path) -> tuple[str, ...]:
    issues = []
    for name, version, expected in COMPONENTS:
        try:
            actual = hashlib.sha256(component_bytes(folder, name)).hexdigest()
        except FileNotFoundError:
            issues.append(localized_text(
                    None, 'toolbox.dlss.neural_profile.t9cb64262',
                    '缺少 {name}（本轮候选 {version}）',
                    name=name, version=version,
                ))
            continue
        except (RuntimeError, zipfile.BadZipFile) as error:
            issues.append(str(error))
            continue
        if actual != expected:
            issues.append(localized_text(
                    None, 'toolbox.dlss.neural_profile.td1ccdf7f',
                    '{name} 与本轮候选哈希不同，暂不自动配置。',
                    name=name,
                ))
    return tuple(issues)


def validate_neural_configuration(data: bytes) -> None:
    values = configuration_values(data)
    if values.get(('ADDON', 'AddonPath'), '') not in {'', '.', './', '.\\'}:
        raise RuntimeError('已有自定义 AddonPath，不属于本轮指定方案；保留原设置，未配置。')


def targets(executable: Path) -> tuple[Path, ...]:
    executable = checked_path(executable)
    if executable.name.casefold() != 'htgame.exe' or not executable.is_file():
        raise RuntimeError('请先在设置中确认 HTGame.exe 路径。')
    game = executable.parent
    if tuple(p.casefold() for p in game.parts[-3:]) != ('ht', 'binaries', 'win64'):
        raise RuntimeError('当前实验仅支持已核对的 HT/Binaries/Win64 布局。')
    dlss = game.parents[2] / 'Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64'
    if not checked_path(dlss / 'nvngx_dlss.dll').is_file():
        raise RuntimeError('未在已知位置找到游戏原生 DLSS；不猜测其他部署目录。')
    return tuple(checked_path(p) for p in (game / 'd3d12.dll', game / CHAIN_HOST,
        game / 'ReShade.ini', game / 'renodx-dlss.addon64', dlss / 'nvngx_dlssnr.dll'))


@dataclass(frozen=True)
class NeuralPlan:
    executable: Path
    changes: tuple[Change, ...]

    @property
    def summary(self) -> str:
        return '\n'.join(f'{"新增" if c.before is None else "备份后替换"}：{c.path}' for c in self.changes)


def plan_install(root: Path, executable: Path, source: Path) -> NeuralPlan:
    issues = inspect_source(source)
    if issues:
        raise RuntimeError('\n'.join(issues))
    proxy, host, ini, addon, nr = targets(executable)
    bundle = inspect_native_plugin_bundle(root)
    if not bundle.ready or bundle.layout not in HOT_PLUGIN_LAYOUTS:
        raise RuntimeError('Calc 配套插件宿主未就绪，请先修复原生组件。')
    existing = inspect_deployed_native_plugin(application_root=root, game_executable_path=executable,
        bundle_inspection=bundle)
    if not existing.files_compatible:
        raise RuntimeError('请先到设置 → 环境部署 Calc 原生组件，再回到这里配置。\n' + '\n'.join(existing.issues))
    for path in proxy.parent.glob('renodx-dlss*.addon64'):
        if path.name.casefold() != addon.name.casefold():
            raise RuntimeError('检测到另一套 RenoDX DLSS 插件，请先自行停用；本工具不混装或删除它。')
    for name in ('dlss5-feed.addon64', 'dlss5-bridge.addon64'):
        if (proxy.parent / name).exists():
            raise RuntimeError(localized_text(
                    None, 'toolbox.dlss.neural_profile.t3b06387b',
                    '检测到 {name}，不属于本轮指定方案；未叠加配置。',
                    name=name,
                ))
    host_source = root / bundle.roles['host']
    host_hash = bundle.files[bundle.roles['host']]
    if file_hash(host_source) != host_hash:
        raise RuntimeError('Calc 随附宿主已改变，请重新检测。')
    if file_hash(host) not in {None, host_hash}:
        raise RuntimeError('串联宿主位置存在其他版本，未覆盖。')
    if file_hash(proxy) not in {host_hash, COMPONENTS[0][2]}:
        raise RuntimeError('已有代理不属于本轮 Calc 或 ReShade 候选，未覆盖。')
    for path, expected in ((addon, COMPONENTS[1][2]), (nr, COMPONENTS[2][2])):
        if file_hash(path) not in {None, expected}:
            raise RuntimeError(localized_text(
                    None, 'toolbox.dlss.neural_profile.t45241d3f',
                    '{name} 已存在其他版本，未覆盖。',
                    name=path.name,
                ))
    frozen = {path: file_hash(path) for path in (proxy, host, ini, addon, nr)}
    # 输入字节在构建计划时冻结；界面确认以后不再读取所选目录中的“最新文件”。
    contents = {name: component_bytes(source, name) for name, _, _ in COMPONENTS}
    if any(hashlib.sha256(contents[name]).hexdigest() != digest for name, _, digest in COMPONENTS):
        raise RuntimeError('所选组件在读取期间改变，请重新检测。')
    before_ini = ini.read_bytes() if ini.exists() else b'[INSTALL]\nLogging=1\n'
    if len(before_ini) > 1024 * 1024:
        raise RuntimeError('ReShade 配置过大，未修改。')
    validate_neural_configuration(before_ini)
    # 串联配置复用已实现的公开 helper，不引入第二套代理配置规则。
    after_ini = configured_bytes(before_ini, allow_setup=True)
    data = ((host, host_source.read_bytes()), (addon, contents['renodx-dlss.addon64']),
            (nr, contents['nvngx_dlssnr.dll']), (ini, after_ini), (proxy, contents['ReShade64.dll']))
    if hashlib.sha256(data[0][1]).hexdigest() != host_hash:
        raise RuntimeError('本方宿主在读取期间改变，未配置。')
    if (any(file_hash(path) != digest for path, digest in frozen.items())
            or (frozen[ini] is not None and hashlib.sha256(before_ini).hexdigest() != frozen[ini])):
        raise RuntimeError('游戏文件或配置在读取期间改变，请重新检测。')
    return NeuralPlan(executable, tuple(Change(path, frozen[path], content) for path, content in data
        if frozen[path] != hashlib.sha256(content).hexdigest()))

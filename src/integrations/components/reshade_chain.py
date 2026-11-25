# 保留玩家 ReShade 入口，通过其公开代理配置串联本方宿主并独立收尾。
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ntpath
import os
from pathlib import Path
import stat
import tempfile

from src.domain.localization.catalog import localized_text
from src.integrations.components.environment import EquipmentPluginDeploymentError
from src.integrations.components.pe_identity import exported_names, is_reshade
from src.integrations.components.native_plugin_bundle import HOT_PLUGIN_LAYOUTS

CHAIN_HOST = 'nte-calc-host.dll'
CONFIG_NAME = 'ReShade.ini'
HOST_EXPORTS = frozenset({'NteCalcHostSignature', 'NteCombatDebugProxySignature'})


def is_calc_host(path: Path) -> bool:
    return HOST_EXPORTS <= exported_names(path)


def regular_path(directory: Path, name: str) -> Path:
    path = directory / name
    try:
        info = path.lstat()
    except FileNotFoundError:
        return path
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
        raise EquipmentPluginDeploymentError(localized_text(
                None, 'toolbox.dlss.reshade_chain.t5b8b4a11',
                '{name} 不是普通文件，已保留现场。',
                name=name,
            ))
    return path


def deployment_paths(bundle, directory: Path) -> dict[str, str]:
    paths = dict(bundle.deployment_paths)
    proxy = regular_path(directory, 'd3d12.dll')
    if is_reshade(proxy):
        if bundle.layout not in HOT_PLUGIN_LAYOUTS:
            raise EquipmentPluginDeploymentError('检测到 ReShade；当前旧采集组件不支持串联，未替换玩家文件。')
        paths['host'] = CHAIN_HOST
    elif regular_path(directory, CHAIN_HOST).exists():
        raise EquipmentPluginDeploymentError('串联宿主仍在，但 ReShade 入口已改变；请先清理计算器组件后重新部署。')
    return paths


def _read_config(directory: Path) -> bytes:
    path = regular_path(directory, CONFIG_NAME)
    if not path.exists():
        raise EquipmentPluginDeploymentError('缺少 ReShade.ini；请先完成 ReShade 安装和首次启动，再部署计算器组件。')
    with path.open('rb') as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise EquipmentPluginDeploymentError('ReShade.ini 超出配置大小限制，未修改。')
    return data


def _parse(data: bytes):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise EquipmentPluginDeploymentError('ReShade.ini 不是可确认的 UTF-8 配置，未修改。') from error
    lines = text.splitlines(keepends=True)
    entries, sections = {}, {}
    section = ''
    for index, line in enumerate(lines):
        value = line.strip()
        if not value or value.startswith((';', '#', '/')):
            continue
        if value.startswith('['):
            if not value.endswith(']'):
                raise EquipmentPluginDeploymentError('ReShade.ini 节格式不明确，未修改。')
            section = value[1:-1].strip()
            if section.casefold() in {key.casefold() for key in sections}:
                raise EquipmentPluginDeploymentError('ReShade.ini 存在重复配置节，未修改。')
            sections[section] = index
        else:
            key, separator, content = value.partition('=')
            key = key.strip()
            identity = (section, key)
            if identity in entries:
                raise EquipmentPluginDeploymentError('ReShade.ini 存在重复配置项，未修改。')
            entries[identity] = (index, content.strip() if separator else '')
    return lines, entries, sections


def _value(entries, section, key):
    return entries.get((section, key), (-1, ''))[1]


def configuration_values(data: bytes) -> dict[tuple[str, str], str]:
    """公开只读配置投影，消费端无需复制 ReShade 的节及重复键校验。"""
    _, entries, _ = _parse(data)
    return {key: value for key, (_, value) in entries.items()}


def _references_host(value: str, directory: Path) -> bool:
    # Windows 路径身份不区分大小写；用户改成绝对路径或 ./ 仍引用同一个宿主。
    return bool(value) and ntpath.normcase(ntpath.normpath(ntpath.join(str(directory), value))) == ntpath.normcase(
        ntpath.normpath(str(directory / CHAIN_HOST)))


def _local_configuration(entries) -> None:
    # BasePath/环境覆盖会改变 ReShade 实际配置所有者；不修改另一个目录的配置。
    if _value(entries, 'INSTALL', 'BasePath') or os.environ.get('RESHADE_BASE_PATH_OVERRIDE'):
        raise EquipmentPluginDeploymentError('ReShade 使用自定义配置目录，当前串联仅支持游戏目录内的 ReShade.ini。')


def chain_configured(directory: Path) -> bool:
    _, entries, _ = _parse(_read_config(directory))
    _local_configuration(entries)
    return (_value(entries, 'PROXY', 'EnableProxyLibrary') == '1'
            and _value(entries, 'PROXY', 'ProxyLibrary') == CHAIN_HOST)


def _encode(lines, original: bytes) -> bytes:
    return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + ''.join(lines).encode('utf-8')


@dataclass(frozen=True)
class ChainPlan:
    directory: Path
    proxy_sha256: str
    before: bytes
    after: bytes

    def check(self, guard, *, committed=False):
        guard()
        proxy = regular_path(self.directory, 'd3d12.dll')
        with proxy.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != self.proxy_sha256 or _read_config(self.directory) != (self.after if committed else self.before):
            raise EquipmentPluginDeploymentError('ReShade 文件或配置在操作期间改变，已停止操作。')

    def commit(self, guard):
        self.check(guard)
        if self.after != self.before:
            _write_config(self.directory, self.before, self.after, lambda: self.check(guard))


def prepare_chain(directory: Path, source: Path, *, allow_setup: bool) -> ChainPlan:
    if not is_calc_host(source):
        raise EquipmentPluginDeploymentError('随附宿主未声明本方插件宿主身份，不能作为 ReShade 串联目标。')
    target = regular_path(directory, CHAIN_HOST)
    if target.exists() and not is_calc_host(target):
        raise EquipmentPluginDeploymentError('nte-calc-host.dll 已被其他文件占用，未覆盖。')
    proxy = regular_path(directory, 'd3d12.dll')
    if not is_reshade(proxy):
        raise EquipmentPluginDeploymentError('ReShade 入口已改变，请重新检测后部署。')
    with proxy.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    before = _read_config(directory)
    return ChainPlan(directory, digest, before, configured_bytes(before, allow_setup=allow_setup))


def configured_bytes(before: bytes, *, allow_setup: bool) -> bytes:
    """冻结配置候选；调用者负责目标文件身份、权限与原子提交。"""
    lines, entries, sections = _parse(before)
    _local_configuration(entries)
    configured = (_value(entries, 'PROXY', 'EnableProxyLibrary') == '1'
                  and _value(entries, 'PROXY', 'ProxyLibrary') == CHAIN_HOST)
    if configured:
        return before
    if not allow_setup:
        raise EquipmentPluginDeploymentError('检测到 ReShade；请在环境设置中点击部署以启用串联，自动更新不会接管其配置。')
    if any(section.casefold() == 'proxy' for section, _ in entries):
        raise EquipmentPluginDeploymentError('ReShade 已有 PROXY 配置，未替换现有串联；请先确认其用途。')
    if any(section.casefold() == 'proxy' and section != 'PROXY' for section in sections):
        raise EquipmentPluginDeploymentError('ReShade PROXY 节大小写不明确，未修改。')
    newline = '\r\n' if b'\r\n' in before else '\n'
    # 只新增我们拥有的两个键；预设、着色器和其他配置字节不经重新序列化。
    insertion = ['EnableProxyLibrary=1' + newline, 'ProxyLibrary=' + CHAIN_HOST + newline]
    if 'PROXY' in sections:
        at = sections['PROXY'] + 1
        if not lines[at - 1].endswith(('\r', '\n')):
            lines[at - 1] += newline
        lines[at:at] = insertion
    else:
        if lines and not lines[-1].endswith(('\r', '\n')):
            lines[-1] += newline
        lines.extend(['[PROXY]' + newline, *insertion])
    return _encode(lines, before)


def detached_bytes(before: bytes, directory: Path) -> bytes:
    lines, entries, _ = _parse(before)
    _local_configuration(entries)
    if not _references_host(_value(entries, 'PROXY', 'ProxyLibrary'), directory):
        return before
    removed = {entries[('PROXY', 'ProxyLibrary')][0]}
    if _value(entries, 'PROXY', 'EnableProxyLibrary') == '1':
        removed.add(entries[('PROXY', 'EnableProxyLibrary')][0])
    return _encode([line for index, line in enumerate(lines) if index not in removed], before)


def _write_config(directory: Path, before: bytes, after: bytes, guard):
    path = regular_path(directory, CONFIG_NAME)
    descriptor, name = tempfile.mkstemp(prefix='.nte-reshade-', suffix='.tmp', dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        guard()
        if _read_config(directory) != before:
            raise EquipmentPluginDeploymentError('ReShade.ini 已改变，未覆盖玩家设置。')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def detach_chain(directory: Path, guard) -> None:
    """先解除确切本方引用，再允许删除宿主；玩家改向其他工具时不改其配置。"""
    _local_configuration({})
    config = regular_path(directory, CONFIG_NAME)
    if not config.exists():
        return
    before = _read_config(directory)
    after = detached_bytes(before, directory)
    if after == before:
        return
    _write_config(directory, before, after, guard)


def require_detached(directory: Path) -> None:
    _local_configuration({})
    if not regular_path(directory, CONFIG_NAME).exists():
        return
    _, entries, _ = _parse(_read_config(directory))
    _local_configuration(entries)
    if _references_host(_value(entries, 'PROXY', 'ProxyLibrary'), directory):
        raise EquipmentPluginDeploymentError('ReShade 仍引用计算器宿主，未删除组件；请重新清理。')

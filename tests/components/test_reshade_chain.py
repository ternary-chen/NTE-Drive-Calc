# 用合成 PE 和临时目录验证 ReShade 串联事务及第三方文件保护，不启动游戏。
from __future__ import annotations

import hashlib
import struct
from types import SimpleNamespace

import pytest

from src.integrations.components import native_files as deployment
from src.integrations.components import reshade_chain as chain
from src.integrations.components.environment import EquipmentPluginDeploymentError
from src.integrations.components.inspection import inspect_deployed_native_plugin
from src.integrations.components.pe_identity import exported_names, is_reshade
from src.integrations.components.native_plugin_bundle import HOT_PLUGIN_DEPLOYMENT_PATHS


def pe_image(*names: str) -> bytes:
    """仅含导出表的不可执行夹具，RVA 固定映射到一个合成节。"""
    image = bytearray(4096)
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 0x3C, 0x80)
    image[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', image, 0x84, 0x8664, 1)
    struct.pack_into('<H', image, 0x94, 240)
    optional = 0x98
    struct.pack_into('<H', image, optional, 0x20B)
    struct.pack_into('<I', image, optional + 60, 512)
    struct.pack_into('<I', image, optional + 108, 16)
    struct.pack_into('<II', image, optional + 112, 0x1000, 40)
    struct.pack_into('<IIII', image, optional + 240 + 8, 3584, 0x1000, 3584, 512)
    struct.pack_into('<I', image, 512 + 24, len(names))
    struct.pack_into('<I', image, 512 + 32, 0x1040)
    offset = 768
    for index, name in enumerate(names):
        struct.pack_into('<I', image, 576 + index * 4, 0x1000 + offset - 512)
        encoded = name.encode('ascii') + b'\0'
        image[offset:offset + len(encoded)] = encoded
        offset += len(encoded)
    return bytes(image)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    root, game = tmp_path / 'package', tmp_path / 'game'
    root.mkdir()
    game.mkdir()
    executable = game / 'HTGame.exe'
    executable.write_bytes(b'fixture only')
    reshade = pe_image('ReShadeVersion', 'D3D12CreateDevice')
    (game / 'd3d12.dll').write_bytes(reshade)
    ini = b'\xef\xbb\xbf[GENERAL]\r\nPresetPath=.\\my-preset.ini\r\n'
    (game / chain.CONFIG_NAME).write_bytes(ini)
    (game / 'my-preset.ini').write_bytes(b'keep preset')
    roles, hashes, sizes = {}, {}, {}
    for role in HOT_PLUGIN_DEPLOYMENT_PATHS:
        source = role + '.dll'
        data = pe_image(*sorted(chain.HOST_EXPORTS)) if role == 'host' else role.encode()
        (root / source).write_bytes(data)
        roles[role], hashes[source], sizes[source] = source, hashlib.sha256(data).hexdigest(), len(data)
    bundle = SimpleNamespace(ready=True, issues=(), roles=roles, files=hashes, file_sizes=sizes,
                             layout='native-plugins-v2', deployment_paths=HOT_PLUGIN_DEPLOYMENT_PATHS,
                             upgrade_from={})
    monkeypatch.setattr(deployment, 'inspect_native_plugin_bundle', lambda _: bundle)
    monkeypatch.delenv('RESHADE_BASE_PATH_OVERRIDE', raising=False)
    return SimpleNamespace(root=root, game=game, executable=executable, bundle=bundle, reshade=reshade, ini=ini)


def deploy(scene, **kwargs):
    return deployment.deploy_native_plugin(
        application_root=scene.root, game_executable_path=scene.executable,
        operation_guard=lambda _: None, game_running=lambda: False, **kwargs,
    )


def test_pe_export_detection_does_not_treat_embedded_text_as_identity(tmp_path):
    path = tmp_path / 'sample.dll'
    path.write_bytes(b'MZ ReShadeVersion fake text')
    assert not is_reshade(path)
    path.write_bytes(pe_image('ReShadeVersion'))
    assert exported_names(path) == frozenset({'ReShadeVersion'})
    damaged = bytearray(path.read_bytes())
    struct.pack_into('<I', damaged, 512 + 24, 0xFFFFFFFF)
    path.write_bytes(damaged)
    assert not is_reshade(path)


def test_first_automatic_deployment_preserves_player_files(scene):
    with pytest.raises(EquipmentPluginDeploymentError, match='显式|点击部署'):
        deploy(scene)
    assert (scene.game / 'd3d12.dll').read_bytes() == scene.reshade
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == scene.ini
    assert not (scene.game / 'plugins').exists()


def test_manual_setup_then_automatic_update_and_cleanup(scene):
    result = deploy(scene, allow_reshade_setup=True)
    assert result.target_path.name == chain.CHAIN_HOST
    assert 'd3d12.dll' not in result.managed_files
    assert (scene.game / 'd3d12.dll').read_bytes() == scene.reshade
    configured = (scene.game / chain.CONFIG_NAME).read_bytes()
    assert configured.startswith(scene.ini)
    assert chain.chain_configured(scene.game)
    inspection = inspect_deployed_native_plugin(
        application_root=scene.root, game_executable_path=scene.executable,
        bundle_inspection=scene.bundle, recorded_files=result.managed_files,
    )
    assert inspection.files_compatible
    assert chain.CHAIN_HOST in inspection.expected_paths
    deploy(scene, expected_existing_files={key: item.sha256 for key, item in inspection.files.items()})
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == configured
    # 兼容用户在计算器部署之后重新安装 ReShade 所留下的旧同名记录。
    result = deployment.cleanup_native_plugin(
        game_executable_path=scene.executable, managed_files={**result.managed_files, 'd3d12.dll': 'old'},
        game_running=lambda: False,
    )
    assert result.status == 'cleaned'
    assert (scene.game / 'd3d12.dll').read_bytes() == scene.reshade
    assert (scene.game / 'my-preset.ini').read_bytes() == b'keep preset'
    assert (scene.game / chain.CONFIG_NAME).read_bytes().startswith(scene.ini)
    assert not chain.chain_configured(scene.game)
    assert not (scene.game / chain.CHAIN_HOST).exists()


def test_inspection_does_not_call_files_ready_when_chain_is_disabled(scene):
    deploy(scene, allow_reshade_setup=True)
    (scene.game / chain.CONFIG_NAME).write_bytes(scene.ini)
    inspection = inspect_deployed_native_plugin(application_root=scene.root,
        game_executable_path=scene.executable, bundle_inspection=scene.bundle)
    assert all(item.matches_bundle for item in inspection.files.values())
    assert not inspection.files_compatible
    assert not inspection.loading_configuration_valid


@pytest.mark.parametrize('extra', [
    b'[PROXY]\nEnableProxyLibrary=1\nProxyLibrary=another.dll\n',
    b'[INSTALL]\nBasePath=elsewhere\n',
    b'[PROXY]\nEnableProxyLibrary=0\nProxyLibrary=old.dll\n',
])
def test_existing_chain_or_external_config_is_not_overwritten(scene, extra):
    before = scene.ini + extra
    (scene.game / chain.CONFIG_NAME).write_bytes(before)
    with pytest.raises(EquipmentPluginDeploymentError):
        deploy(scene, allow_reshade_setup=True)
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == before
    assert not (scene.game / chain.CHAIN_HOST).exists()
    assert not (scene.game / 'plugins').exists()


def test_replaced_config_stops_commit_without_losing_player_changes(scene):
    plan = chain.prepare_chain(scene.game, scene.root / scene.bundle.roles['host'], allow_setup=True)
    changed = scene.ini + b'PlayerChanged=1\n'
    (scene.game / chain.CONFIG_NAME).write_bytes(changed)
    with pytest.raises(EquipmentPluginDeploymentError, match='改变'):
        plan.commit(lambda: None)
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == changed


def test_write_failure_keeps_recoverable_component_record(scene, monkeypatch):
    def failed(*args):
        raise OSError('fixture config write failed')
    monkeypatch.setattr(chain, '_write_config', failed)
    with pytest.raises(deployment.PluginDeploymentPendingCleanup) as error:
        deploy(scene, allow_reshade_setup=True)
    assert chain.CHAIN_HOST in error.value.deployment.managed_files
    assert (scene.game / 'd3d12.dll').read_bytes() == scene.reshade
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == scene.ini


def test_manual_cleanup_preserves_unrecorded_reshade(scene):
    result = deployment.cleanup_manual_native_plugin(application_root=scene.root,
        game_executable_path=scene.executable, managed_files={}, game_running=lambda: False)
    assert result.status == 'cleaned'
    assert (scene.game / 'd3d12.dll').read_bytes() == scene.reshade
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == scene.ini


def test_cleanup_preserves_new_user_settings_and_recognizes_windows_path_identity(scene):
    deployed = deploy(scene, allow_reshade_setup=True)
    config = scene.game / chain.CONFIG_NAME
    config.write_bytes(config.read_bytes().replace(b'ProxyLibrary=nte-calc-host.dll',
        b'ProxyLibrary=.\\NTE-CALC-HOST.DLL') + b'[PLAYER]\r\nChanged=1\r\n')
    result = deployment.cleanup_native_plugin(game_executable_path=scene.executable,
        managed_files=deployed.managed_files, game_running=lambda: False)
    assert result.status == 'cleaned'
    assert b'[PLAYER]\r\nChanged=1\r\n' in config.read_bytes()
    assert b'ProxyLibrary=' not in config.read_bytes()


def test_unknown_alternate_host_is_neither_replaced_nor_removed(scene):
    occupied = scene.game / chain.CHAIN_HOST
    occupied.write_bytes(b'player file')
    with pytest.raises(EquipmentPluginDeploymentError, match='占用'):
        deploy(scene, allow_reshade_setup=True)
    result = deployment.cleanup_manual_native_plugin(application_root=scene.root,
        game_executable_path=scene.executable, managed_files={}, game_running=lambda: False)
    assert result.status == 'conflict'
    assert occupied.read_bytes() == b'player file'


def test_game_running_and_revocation_prevent_config_mutation(scene):
    with pytest.raises(EquipmentPluginDeploymentError, match='游戏正在运行'):
        deployment.deploy_native_plugin(application_root=scene.root, game_executable_path=scene.executable,
            operation_guard=lambda _: None, game_running=lambda: True, allow_reshade_setup=True)
    plan = chain.prepare_chain(scene.game, scene.root / scene.bundle.roles['host'], allow_setup=True)
    def revoked():
        raise PermissionError('revoked')
    with pytest.raises(PermissionError):
        plan.commit(revoked)
    assert (scene.game / chain.CONFIG_NAME).read_bytes() == scene.ini


def test_external_config_override_blocks_cleanup_even_without_local_ini(scene, monkeypatch):
    deployed = deploy(scene, allow_reshade_setup=True)
    (scene.game / chain.CONFIG_NAME).unlink()
    monkeypatch.setenv('RESHADE_BASE_PATH_OVERRIDE', str(scene.game / 'external'))
    result = deployment.cleanup_native_plugin(game_executable_path=scene.executable,
        managed_files=deployed.managed_files, game_running=lambda: False)
    assert result.status == 'conflict'
    assert (scene.game / chain.CHAIN_HOST).exists()

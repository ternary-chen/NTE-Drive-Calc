# 验证实验组件的冻结写入、恢复与玩家配置保护，不启动游戏。
import hashlib

import pytest

from src.integrations.components.neural_transaction import Change, FileTransaction


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_apply_restore_preserves_original_and_removes_only_owned_new_files(tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    host, addon = game / 'd3d12.dll', game / 'renodx-dlss.addon64'
    host.write_bytes(b'calc')
    tx = FileTransaction(tmp_path / 'state', (host, addon))
    tx.apply((Change(host, digest(b'calc'), b'reshade'), Change(addon, None, b'addon')), lambda: None)
    assert host.read_bytes() == b'reshade'
    assert tx.status() == 'configured'
    tx.restore(lambda: None)
    assert host.read_bytes() == b'calc'
    assert not addon.exists()
    assert tx.status() == 'restored'


def test_changed_target_blocks_all_restoration_before_any_delete(tmp_path):
    a, b = tmp_path / 'a.dll', tmp_path / 'b.dll'
    tx = FileTransaction(tmp_path / 'state', (a, b))
    tx.apply((Change(a, None, b'a'), Change(b, None, b'b')), lambda: None)
    a.write_bytes(b'player edit')
    with pytest.raises(RuntimeError, match='改变'):
        tx.restore(lambda: None)
    assert b.read_bytes() == b'b'


def test_interrupted_install_remains_recoverable(tmp_path):
    a, b = tmp_path / 'a.dll', tmp_path / 'b.dll'
    tx = FileTransaction(tmp_path / 'state', (a, b))
    def guard():
        if a.exists():
            raise PermissionError('revoked')
    with pytest.raises(PermissionError):
        tx.apply((Change(a, None, b'a'), Change(b, None, b'b')), guard)
    assert tx.status() == 'pending'
    tx.restore(lambda: None)
    assert not a.exists() and not b.exists()


def test_frozen_target_change_prevents_install(tmp_path):
    a = tmp_path / 'a.dll'
    a.write_bytes(b'player')
    tx = FileTransaction(tmp_path / 'state', (a,))
    with pytest.raises(RuntimeError, match='改变'):
        tx.apply((Change(a, None, b'new'),), lambda: None)
    assert a.read_bytes() == b'player'


def test_configuration_edits_survive_restore(tmp_path):
    ini = tmp_path / 'ReShade.ini'
    tx = FileTransaction(tmp_path / 'state', (ini,))
    after = b'[PROXY]\nEnableProxyLibrary=1\nProxyLibrary=nte-calc-host.dll\n'
    tx.apply((Change(ini, None, after),), lambda: None)
    ini.write_bytes(after + b'[USER]\nPreset=mine\n')
    tx.restore(lambda: None)
    assert b'Preset=mine' in ini.read_bytes()
    assert b'ProxyLibrary=' not in ini.read_bytes()


def test_journal_cannot_expand_allowed_paths(tmp_path):
    import json
    owned, foreign = tmp_path / 'owned.dll', tmp_path / 'foreign.dll'
    foreign.write_bytes(b'keep')
    tx = FileTransaction(tmp_path / 'state', (owned,))
    tx.apply((Change(owned, None, b'ours'),), lambda: None)
    record = json.loads(tx.journal.read_text(encoding='utf-8'))
    record['entries'][0]['path'] = str(foreign)
    tx.journal.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(RuntimeError):
        tx.restore(lambda: None)
    assert foreign.read_bytes() == b'keep'


def test_profile_freezes_bytes_and_keeps_game_original_dlss(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.integrations.components import neural_profile as profile
    game = tmp_path / 'WindowsNoEditor/HT/Binaries/Win64'
    dlss = tmp_path / 'WindowsNoEditor/Engine/Plugins/Runtime/Nvidia/DLSS/Binaries/ThirdParty/Win64'
    source, root = tmp_path / 'input', tmp_path / 'bundle'
    for directory in (game, dlss, source, root):
        directory.mkdir(parents=True)
    executable = game / 'HTGame.exe'
    executable.write_bytes(b'fixture game')
    (dlss / 'nvngx_dlss.dll').write_bytes(b'original dlss')
    (root / 'host.dll').write_bytes(b'calc host')
    (game / 'd3d12.dll').write_bytes(b'calc host')
    candidates = [('ReShade64.dll', b'reshade'), ('renodx-dlss.addon64', b'addon'), ('nvngx_dlssnr.dll', b'nr')]
    for name, data in candidates:
        (source / name).write_bytes(data)
    monkeypatch.setattr(profile, 'COMPONENTS', tuple((name, 'fixture', digest(data)) for name, data in candidates))
    monkeypatch.setattr(profile, 'inspect_native_plugin_bundle', lambda _: SimpleNamespace(
        ready=True, layout='native-plugins-v3', roles={'host': 'host.dll'}, files={'host.dll': digest(b'calc host')}))
    monkeypatch.setattr(profile, 'inspect_deployed_native_plugin', lambda **_: SimpleNamespace(files_compatible=True))
    plan = profile.plan_install(root, executable, source)
    (source / 'nvngx_dlssnr.dll').write_bytes(b'later source')
    assert next(c.data for c in plan.changes if c.path.name == 'nvngx_dlssnr.dll') == b'nr'
    tx = FileTransaction(tmp_path / 'state', profile.targets(executable))
    tx.apply(plan.changes, lambda: None)
    assert (dlss / 'nvngx_dlss.dll').read_bytes() == b'original dlss'
    tx.restore(lambda: None)
    assert (game / 'd3d12.dll').read_bytes() == b'calc host'
    assert (dlss / 'nvngx_dlss.dll').read_bytes() == b'original dlss'


def test_service_rejects_game_running_and_stale_generation(tmp_path):
    from src.services.components.neural_rendering import NeuralRenderingService
    generation = [1]
    service = NeuralRenderingService(root=tmp_path, config=tmp_path,
        game_path=lambda: str(tmp_path / 'HTGame.exe'), guard=lambda _: None,
        generation=lambda: generation[0], game_running=lambda: False)
    _, guard = service.freeze_guard()
    generation[0] = 2
    with pytest.raises(RuntimeError, match='改变'):
        guard()
    service.game_running = lambda: True
    with pytest.raises(RuntimeError, match='游戏已退出'):
        service.freeze_guard()


def test_recovery_does_not_accept_corrupt_backup(tmp_path):
    import json
    host = tmp_path / 'd3d12.dll'
    host.write_bytes(b'old')
    tx = FileTransaction(tmp_path / 'state', (host,))
    tx.apply((Change(host, digest(b'old'), b'new'),), lambda: None)
    record = json.loads(tx.journal.read_text(encoding='utf-8'))
    (tx.state / record['transaction'] / '0.bin').write_bytes(b'corrupt')
    with pytest.raises(RuntimeError, match='副本损坏'):
        tx.restore(lambda: None)
    assert host.read_bytes() == b'new'


def test_installer_is_read_as_archive_and_never_executed(tmp_path, monkeypatch):
    import zipfile
    from src.integrations.components import neural_profile as profile
    installer = tmp_path / 'ReShade_Setup_fixture.exe'
    with zipfile.ZipFile(installer, 'w') as archive:
        archive.writestr('ReShade64.dll', b'fixture reshade')
        archive.writestr('../unrelated.exe', b'not extracted')
    monkeypatch.setattr(profile, 'ARCHIVES', {'ReShade64.dll': (installer.name, digest(installer.read_bytes()))})
    assert profile.component_bytes(tmp_path, 'ReShade64.dll') == b'fixture reshade'
    assert not (tmp_path / 'ReShade64.dll').exists()
    assert not (tmp_path.parent / 'unrelated.exe').exists()
    installer.write_bytes(b'changed archive')
    with pytest.raises(RuntimeError, match='不同'):
        profile.component_bytes(tmp_path, 'ReShade64.dll')


def test_user_component_directory_is_created_only_on_explicit_request(tmp_path):
    from src.services.components.neural_rendering import NeuralRenderingService
    directory = tmp_path / 'user-components/neural-rendering'
    service = NeuralRenderingService(root=tmp_path, config=tmp_path / 'config', game_path=lambda: '',
        guard=lambda _: None, generation=lambda: 1, component_directory=directory)
    assert not directory.exists()
    assert service.prepare_directory() == str(directory)
    assert directory.is_dir()


def test_fixed_profile_rejects_custom_addon_directory_without_rewriting():
    from src.integrations.components.neural_profile import validate_neural_configuration
    with pytest.raises(RuntimeError, match='AddonPath'):
        validate_neural_configuration(b'[ADDON]\nAddonPath=another-folder\n')
    validate_neural_configuration(b'[ADDON]\nAddonPath=.\n')


@pytest.mark.parametrize('account_changed', [False, True])
def test_maintenance_records_real_host_and_releases_on_same_or_changed_account(tmp_path, monkeypatch, account_changed):
    from types import SimpleNamespace as NS
    from src.ui.composition import neural_composition as composition
    calls, generation = [], [1]
    executable = tmp_path / 'HTGame.exe'
    lease = NS(close=lambda: calls.append('released'), disconnect=lambda **_: None)
    owner = NS(suspend_for_plugin_update=lambda: None,
        resume_after_plugin_update=lambda **kw: calls.append(('resume', kw['restore'])),
        wait_plugin_update_idle=lambda: True)
    def save(record):
        calls.append(('save', record.target_path.name))
        generation[0] += 1  # 本次部署记录更新也可能推进模式操作版本。
    window = NS(app_context=NS(paths=NS(root=tmp_path, config_dir=tmp_path / 'config', data_root=tmp_path)),
        work_mode_service=NS(settings=NS(paused=False, pending_cleanup=False, game_executable=str(executable)),
                             deployment_record={}), native_game_session=NS(reserve_plugin_maintenance=lambda: lease),
        operation_guard=lambda _: None, operation_generation=lambda: generation[0],
        _mod_plugin_loading_service=NS(snapshot=lambda: NS(phase='stopped')),
        work_mode_controller=NS(is_transitioning=False), global_hotkey_manager=NS(active_owner=None),
        auto_sync_controller=owner, performance_controller=owner,
        work_mode_runtime=NS(save_deployment=save, invalidate=lambda: None), _go=lambda _: None)
    monkeypatch.setattr(composition, 'inspect_deployed_native_plugin', lambda **_: NS(files_compatible=True,
        files={'nte-calc-host.dll': NS(sha256='fixture')}, layout='native-plugins-v3'))
    dependencies = composition.build_neural_dependencies(window)
    maintenance = dependencies.begin()
    if account_changed:
        generation[0] += 1
    dependencies.finish(maintenance)
    assert 'released' in calls
    assert ('resume', not account_changed) in calls
    assert (('save', 'nte-calc-host.dll') in calls) is not account_changed

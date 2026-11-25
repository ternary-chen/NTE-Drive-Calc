# 对实验图形组件建立精确文件日志与恢复副本，中断后按实际字节恢复。
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
from uuid import uuid4

from src.domain.localization.catalog import localized_text
from src.integrations.components.reshade_chain import detached_bytes, regular_path


def file_hash(path: Path) -> str | None:
    regular_path(path.parent, path.name)
    if not path.exists():
        return None
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(path: Path) -> Path:
    if not path.is_absolute() or '..' in path.parts:
        raise RuntimeError('组件目标必须是明确的绝对路径。')
    for parent in (path, *path.parents):
        if parent.is_symlink() or (parent.exists() and getattr(parent.lstat(), 'st_file_attributes', 0)
                                   & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            raise RuntimeError('组件路径含链接或重解析目录，未操作。')
    regular_path(path.parent, path.name)
    return path


def replace_bytes(path: Path, data: bytes, before: str | None, guard) -> None:
    checked_path(path)
    descriptor, name = tempfile.mkstemp(prefix='.nte-neural-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        guard()
        checked_path(path)
        if file_hash(path) != before:
            raise RuntimeError(localized_text(
                    None, 'toolbox.dlss.neural_transaction.t4bf12be1',
                    '{name} 在操作期间改变，已保留现场。',
                    name=path.name,
                ))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class Change:
    path: Path
    before: str | None
    data: bytes


class FileTransaction:
    """日志先于游戏写入；恢复不依赖某个内存回调是否已经执行。"""

    def __init__(self, state: Path, allowed: tuple[Path, ...]):
        self.state = state.absolute()
        self.journal = self.state / 'active.json'
        self.allowed = {os.path.normcase(str(path.absolute())) for path in allowed}

    def _save(self, record):
        self.state.mkdir(parents=True, exist_ok=True)
        replace_bytes(self.journal, json.dumps(record, ensure_ascii=False, indent=2).encode('utf-8'),
                      file_hash(self.journal), lambda: None)

    def _read(self):
        checked_path(self.journal)
        if not self.journal.exists():
            return None
        if self.journal.stat().st_size > 1024 * 1024:
            raise RuntimeError('组件恢复记录过大，未操作。')
        record = json.loads(self.journal.read_text(encoding='utf-8'))
        if (record.get('schema') != 1 or record.get('status') not in {'pending', 'configured', 'restored'}
                or not isinstance(record.get('entries'), list) or len(record['entries']) > 8):
            raise RuntimeError('组件恢复记录格式不匹配。')
        transaction = record.get('transaction', '')
        if len(transaction) != 32 or any(c not in '0123456789abcdef' for c in transaction):
            raise RuntimeError('组件恢复目录身份不匹配。')
        seen = set()
        for index, entry in enumerate(record['entries']):
            path = checked_path(Path(entry['path']))
            identity = os.path.normcase(str(path))
            if identity not in self.allowed or identity in seen:
                raise RuntimeError('组件恢复记录包含本次范围外或重复的文件。')
            seen.add(identity)
            for key in ('before', 'after'):
                digest = entry.get(key)
                if digest is None and key == 'before':
                    continue
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise RuntimeError('组件恢复记录哈希无效。')
            if entry.get('backup') != (f'{index}.bin' if entry['before'] is not None else None):
                raise RuntimeError('组件恢复副本名称无效。')
        return record

    def status(self) -> str:
        record = self._read()
        if record is None:
            return 'absent'
        if record['status'] == 'configured' and any(
            file_hash(Path(e['path'])) != e['after'] for e in record['entries']
        ):
            return 'changed'
        return record['status']

    def apply(self, changes: tuple[Change, ...], guard) -> None:
        guard()
        previous = self._read()
        if previous and previous['status'] != 'restored':
            raise RuntimeError('已有实验配置或未完成事务，请先检查或恢复本次配置。')
        changes = tuple(c for c in changes if c.before != hashlib.sha256(c.data).hexdigest())
        if not changes:
            raise RuntimeError('目标已包含所选组件，没有可由本次接管的更改。')
        seen = set()
        for change in changes:
            identity = os.path.normcase(str(checked_path(change.path)))
            if identity not in self.allowed or identity in seen:
                raise RuntimeError('组件计划包含范围外或重复目标。')
            seen.add(identity)
            if file_hash(change.path) != change.before:
                raise RuntimeError('组件目标已改变，请重新检测。')
        transaction = uuid4().hex
        backup = self.state / transaction
        backup.mkdir(parents=True)
        record = {'schema': 1, 'status': 'pending', 'transaction': transaction, 'entries': []}
        for index, change in enumerate(changes):
            guard()
            backup_name = None
            if change.before is not None:
                original = change.path.read_bytes()
                if hashlib.sha256(original).hexdigest() != change.before:
                    raise RuntimeError('组件备份时目标已改变，未写游戏文件。')
                backup_name = f'{index}.bin'
                (backup / backup_name).write_bytes(original)
            record['entries'].append({'path': str(change.path), 'before': change.before,
                'after': hashlib.sha256(change.data).hexdigest(), 'backup': backup_name})
        self._save(record)
        for change in changes:
            replace_bytes(change.path, change.data, change.before, guard)
        guard()
        record['status'] = 'configured'
        self._save(record)

    def restore(self, guard) -> None:
        guard()
        record = self._read()
        if record is None or record['status'] == 'restored':
            raise RuntimeError('没有本次配置可恢复。')
        planned = []
        # 全部预检通过后才恢复第一份文件；配置只撤销本方引用，保留游戏内新保存的偏好。
        for entry in reversed(record['entries']):
            path = Path(entry['path'])
            current = file_hash(path)
            if current == entry['before']:
                continue
            if current != entry['after']:
                if path.name == 'ReShade.ini' and current is not None:
                    content = path.read_bytes()
                    if len(content) > 1024 * 1024 or hashlib.sha256(content).hexdigest() != current:
                        raise RuntimeError('ReShade 配置已改变，未恢复。')
                    planned.append((path, current, detached_bytes(content, path.parent)))
                    continue
                raise RuntimeError(localized_text(
                        None, 'toolbox.dlss.neural_transaction.t027d8d28',
                        '{name} 已改变，未覆盖玩家文件；请查看恢复记录。',
                        name=path.name,
                    ))
            data = None
            if entry['before'] is not None:
                backup = checked_path(self.state / record['transaction'] / entry['backup'])
                if file_hash(backup) != entry['before']:
                    raise RuntimeError('恢复副本损坏，未操作游戏文件。')
                data = backup.read_bytes()
            planned.append((path, current, data))
        for path, current, data in planned:
            guard()
            if file_hash(checked_path(path)) != current:
                raise RuntimeError('恢复期间文件改变，剩余内容已保留。')
            if data is None:
                path.unlink()
            else:
                replace_bytes(path, data, current, guard)
        record['status'] = 'restored'
        self._save(record)

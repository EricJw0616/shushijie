#!/usr/bin/env python3
"""Relocate embedded file paths in a copied deployment dataset, never the source."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile


BACKUPS = '.migration-backups'


class MigrationError(ValueError):
    """The dataset cannot be migrated safely without operator intervention."""


@dataclass
class Change:
    path: Path
    relative: Path
    before: bytes
    after: bytes
    count: int
    mode: int


def _inside(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _roots(data_root, source_root, target_root):
    for name, value in (('data-root', data_root), ('source-root', source_root), ('target-root', target_root)):
        if not Path(value).is_absolute():
            raise MigrationError('--%s must be an absolute path' % name)
    data = Path(data_root).resolve()
    source = Path(source_root).resolve()
    if _inside(data, source):
        raise MigrationError('data-root must be a separate copy outside source-root')
    if not data.is_dir():
        raise MigrationError('data-root must be an existing directory')
    # Match the original path spelling, not this machine's symlink expansion.
    source_prefix = os.path.normpath(str(source_root)).rstrip('/') + '/'
    target_prefix = os.path.normpath(str(target_root)).rstrip('/') + '/'
    if source_prefix == target_prefix:
        raise MigrationError('source-root and target-root must differ')
    return data, source_prefix, target_prefix


def _relocate(value, source_prefix, target_prefix):
    if isinstance(value, str):
        if value.startswith(source_prefix):
            return target_prefix + value[len(source_prefix):], 1
        return value, 0
    if isinstance(value, list):
        result, total = [], 0
        for item in value:
            changed, count = _relocate(item, source_prefix, target_prefix)
            result.append(changed)
            total += count
        return result, total
    if isinstance(value, dict):
        result, total = {}, 0
        for key, item in value.items():
            changed, count = _relocate(item, source_prefix, target_prefix)
            result[key] = changed  # JSON object keys are not path values.
            total += count
        return result, total
    return value, 0


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def _invalid_constant(_value):
    raise ValueError('nonstandard JSON number')


def _parse(text):
    return json.loads(text, object_pairs_hook=_object, parse_constant=_invalid_constant)


def _transform(raw, jsonl, source_prefix, target_prefix):
    bom = raw.startswith(b'\xef\xbb\xbf')
    text = raw.decode('utf-8-sig')
    total = 0
    if jsonl:
        parts = []
        for line in text.splitlines(keepends=True):
            if not line.strip():
                parts.append(line)
                continue
            value, count = _relocate(_parse(line), source_prefix, target_prefix)
            total += count
            if count:
                ending = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
                parts.append(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + ending)
            else:
                parts.append(line)
        output = ''.join(parts)
    else:
        value, total = _relocate(_parse(text), source_prefix, target_prefix)
        newline = '\r\n' if '\r\n' in text else '\n'
        output = json.dumps(value, ensure_ascii=False, indent=2).replace('\n', newline)
        if text.endswith('\n'):
            output += newline
    if not total:
        return raw, 0
    return (b'\xef\xbb\xbf' if bom else b'') + output.encode('utf-8'), total


def plan(data_root, source_root, target_root):
    """Read and validate every JSON file before allowing any migration writes."""
    data, source_prefix, target_prefix = _roots(data_root, source_root, target_root)
    changes, scanned = [], 0
    for folder, directories, filenames in os.walk(data, followlinks=False):
        directories[:] = sorted(d for d in directories
                                if d != BACKUPS and not (Path(folder) / d).is_symlink())
        for filename in sorted(filenames):
            path = Path(folder) / filename
            if path.suffix.lower() not in ('.json', '.jsonl'):
                continue
            relative = path.relative_to(data)
            if path.is_symlink() or not _inside(path.resolve(), data):
                raise MigrationError('Refusing linked JSON file: %s' % relative)
            try:
                raw = path.read_bytes()
                after, count = _transform(raw, path.suffix.lower() == '.jsonl', source_prefix, target_prefix)
                mode = stat.S_IMODE(path.stat().st_mode)
            except (OSError, UnicodeError, ValueError) as error:
                # Do not echo parser details: they can include application data.
                raise MigrationError('Cannot read valid JSON: %s (%s)' %
                                     (relative, type(error).__name__)) from None
            scanned += 1
            if count:
                changes.append(Change(path, relative, raw, after, count, mode))
    return data, scanned, changes


def _atomic_write(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix='.relocate-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), mode)
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate(data_root, source_root, target_root, apply=False):
    data, scanned, changes = plan(data_root, source_root, target_root)
    report = {'mode': 'apply' if apply else 'dry-run', 'scanned_files': scanned,
              'changed_files': len(changes), 'changed_paths': sum(c.count for c in changes)}
    if not apply or not changes:
        return report
    # Detect a concurrent edit before producing any backups or replacing files.
    for change in changes:
        if (change.path.is_symlink() or not _inside(change.path.resolve(), data)
                or change.path.read_bytes() != change.before):
            raise MigrationError('Dataset changed during preflight: %s' % change.relative)
    backup_parent = data / BACKUPS
    if backup_parent.is_symlink():
        raise MigrationError('Backup directory must not be a symbolic link')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + secrets.token_hex(3)
    backup = backup_parent / stamp
    backup.mkdir(parents=True, mode=0o700)
    # Save every original byte sequence before replacing the first data file.
    for change in changes:
        saved = backup / change.relative
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with saved.open('xb') as output:
            output.write(change.before)
            output.flush()
            os.fchmod(output.fileno(), change.mode)
            os.fsync(output.fileno())
    for change in changes:
        if (change.path.is_symlink() or not _inside(change.path.resolve(), data)
                or change.path.read_bytes() != change.before):
            raise MigrationError('Dataset changed during apply; originals retained in backup: %s' % change.relative)
        _atomic_write(change.path, change.after, change.mode)
    report['backup_directory'] = str(backup)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, help='Copied dataset root, outside the source project')
    parser.add_argument('--source-root', required=True, help='Original absolute project path embedded in data')
    parser.add_argument('--target-root', required=True, help='Absolute project path inside the container')
    parser.add_argument('--apply', action='store_true', help='Write changes after validation; default is dry-run')
    args = parser.parse_args(argv)
    try:
        report = migrate(args.data_root, args.source_root, args.target_root, apply=args.apply)
    except (MigrationError, OSError) as error:
        print('Migration stopped: %s' % error, file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

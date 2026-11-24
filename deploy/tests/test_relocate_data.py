"""Copied deployment data gets bounded path changes and byte-exact backups."""

import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'relocate_data.py'
spec = importlib.util.spec_from_file_location('relocate_data', SCRIPT)
relocate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = relocate
spec.loader.exec_module(relocate)


class RelocateDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / '本机工程'
        self.source.mkdir()
        self.data = self.root / 'deployment-copy'
        self.data.mkdir()
        self.target = '/app'

    def write(self, name, content):
        path = self.data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path

    def run_migration(self, apply=False):
        return relocate.migrate(self.data, self.source, self.target, apply=apply)

    def test_cli_defaults_to_readonly_and_does_not_print_data(self):
        path = self.write('app-data/jobs/job.json', json.dumps({'source_path': str(self.source / 'app/data/private.pdf')}))
        before = path.read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), '--data-root', str(self.data),
                                 '--source-root', str(self.source), '--target-root', '/app'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'mode': 'dry-run', 'scanned_files': 1,
                                                    'changed_files': 1, 'changed_paths': 1})
        self.assertNotIn('private.pdf', result.stdout)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.data / relocate.BACKUPS).exists())

    def test_apply_changes_only_string_value_prefixes_and_backs_up_original_bytes(self):
        prefix = str(self.source)
        original = {'source': prefix + '/app/data/book.pdf', 'nested': [{'raw': prefix + '/书库分类/raw/书.txt'}],
                    'root_only': prefix, 'similar': prefix + '-backup/file',
                    'log': 'Read source at ' + prefix + '/book.pdf', prefix + '/key': 'unchanged',
                    'number': 42, 'boolean': True, 'nothing': None}
        path = self.write('app-data/jobs/one.json', json.dumps(original, ensure_ascii=False, indent=1) + '\n')
        path.chmod(0o640)
        before = path.read_bytes()
        report = self.run_migration(apply=True)
        changed = json.loads(path.read_bytes())
        self.assertEqual(changed['source'], '/app/app/data/book.pdf')
        self.assertEqual(changed['nested'], [{'raw': '/app/书库分类/raw/书.txt'}])
        for key in ('root_only', 'similar', 'log', prefix + '/key', 'number', 'boolean', 'nothing'):
            self.assertEqual(changed[key], original[key])
        self.assertEqual(report['changed_paths'], 2)
        self.assertEqual(report['changed_files'], 1)
        backup = Path(report['backup_directory']) / path.relative_to(self.data)
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)
        self.assertEqual(self.run_migration(apply=True)['changed_files'], 0)

    def test_jsonl_keeps_blank_and_unchanged_lines_and_skips_log_files(self):
        first = json.dumps({'path': str(self.source / 'file')}) + '\r\n'
        remainder = '\r\n { "message" : "unchanged" }\n42'
        path = self.write('library/segments.jsonl', first + remainder)
        log = self.write('app-data/jobs/run.log', str(self.source / 'file'))
        report = self.run_migration(apply=True)
        self.assertEqual(report['scanned_files'], 1)
        self.assertEqual(path.read_bytes(), b'{"path":"/app/file"}\r\n' + remainder.encode())
        self.assertEqual(log.read_text(), str(self.source / 'file'))

    def test_malformed_json_prevents_all_changes_and_backups(self):
        good = self.write('config/a.json', json.dumps({'file': str(self.source / 'file')}))
        bad = self.write('config/z.json', '{"secret":"sensitive content", broken')
        before = good.read_bytes(), bad.read_bytes()
        with self.assertRaisesRegex(relocate.MigrationError, 'valid JSON') as caught:
            self.run_migration(apply=True)
        self.assertNotIn('sensitive content', str(caught.exception))
        self.assertEqual((good.read_bytes(), bad.read_bytes()), before)
        self.assertFalse((self.data / relocate.BACKUPS).exists())

    def test_malformed_jsonl_duplicate_keys_and_invalid_utf8_are_not_rewritten(self):
        for content in (b'{"path":"x"}\nnot-json\n', b'{"x":1,"x":2}', b'\xff', b'{"x":NaN}'):
            with self.subTest(content=content):
                path = self.write('out/invalid.jsonl', content)
                with self.assertRaises(relocate.MigrationError):
                    self.run_migration(apply=True)
                self.assertEqual(path.read_bytes(), content)

    def test_refuses_source_root_descendants_and_symlink_alias(self):
        descendant = self.source / 'copy'; descendant.mkdir()
        alias = self.root / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        for data in (self.source, descendant, alias):
            with self.subTest(data=data), self.assertRaisesRegex(relocate.MigrationError, 'outside source-root'):
                relocate.migrate(data, self.source, self.target, apply=True)

    def test_refuses_json_symlinks_and_never_traverses_linked_directories(self):
        original = self.source / 'original.json'
        original.write_text(json.dumps({'path': str(self.source / 'file')}))
        linked = self.data / 'linked.json'; linked.symlink_to(original)
        with self.assertRaisesRegex(relocate.MigrationError, 'linked JSON'):
            self.run_migration(apply=True)
        linked.unlink()
        (self.data / 'linked-folder').symlink_to(self.source, target_is_directory=True)
        self.assertEqual(self.run_migration(apply=True)['scanned_files'], 0)
        self.assertEqual(json.loads(original.read_text())['path'], str(self.source / 'file'))

    def test_failed_atomic_replace_keeps_original_and_backup(self):
        path = self.write('books/one.json', json.dumps({'path': str(self.source / 'file')}))
        before = path.read_bytes()
        with patch.object(relocate.os, 'replace', side_effect=OSError('test replace failure')):
            with self.assertRaises(OSError):
                self.run_migration(apply=True)
        self.assertEqual(path.read_bytes(), before)
        backups = list((self.data / relocate.BACKUPS).glob('*/books/one.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(list(path.parent.glob('.relocate-*')), [])

    def test_backups_are_excluded_and_relative_roots_are_rejected(self):
        self.write('.migration-backups/earlier/invalid.json', 'not-json')
        self.assertEqual(self.run_migration()['scanned_files'], 0)
        for data, source, target in (('relative', self.source, '/app'),
                                     (self.data, 'relative', '/app'), (self.data, self.source, 'relative')):
            with self.assertRaisesRegex(relocate.MigrationError, 'absolute path'):
                relocate.migrate(data, source, target)


if __name__ == '__main__':
    unittest.main()

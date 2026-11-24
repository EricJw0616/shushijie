"""Launcher chooses one environment and preflights PDFs without network or project writes."""
import contextlib
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as launcher


class LauncherTests(unittest.TestCase):
    def test_posix_venv_symlink_is_not_mistaken_for_system_python(self):
        with tempfile.TemporaryDirectory(prefix='launcher with spaces ') as folder:
            root = Path(folder)
            executable = root / '.venv' / 'bin' / 'python'
            executable.parent.mkdir(parents=True)
            executable.symlink_to(sys.executable)
            self.assertEqual(launcher._project_python(root, prefix='/usr', platform='posix'), executable)
            self.assertIsNone(launcher._project_python(root, prefix=root / '.venv', platform='posix'))

    def test_windows_uses_scripts_python_without_needing_posix_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / '.venv' / 'Scripts' / 'python.exe'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'placeholder')
            self.assertEqual(launcher._project_python(root, prefix=root, platform='nt'), executable)
            self.assertIsNone(launcher._project_python(root, prefix=root / '.venv', platform='nt'))

    def test_no_venv_keeps_current_environment_without_creating_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(launcher._project_python(root, prefix='/usr', platform='posix'))
            self.assertFalse((root / '.venv').exists())

    def test_rerun_preserves_arguments_and_paths_with_spaces(self):
        child = Mock()
        child.wait.return_value = 7
        interpreter = Path('/project with spaces/.venv/bin/python')
        with patch.object(launcher.os, 'name', 'nt'), patch.object(launcher.subprocess, 'Popen', return_value=child) as popen:
            self.assertEqual(launcher._rerun(interpreter, ['--host', '0.0.0.0', '--port', '8943']), 7)
        popen.assert_called_once_with(
            [str(interpreter), str(launcher.APP_DIR / 'run.py'), '--host', '0.0.0.0', '--port', '8943'],
            cwd=str(launcher.PROJECT_ROOT))

    def test_rerun_failure_does_not_replace_or_install_environment(self):
        stderr = StringIO()
        interpreter = Path('/unavailable/python')
        with patch.object(launcher.os, 'name', 'nt'), patch.object(launcher.subprocess, 'Popen', side_effect=OSError('cannot execute')), contextlib.redirect_stderr(stderr):
            self.assertEqual(launcher._rerun(interpreter, ['--check']), 2)
        self.assertIn('.venv', stderr.getvalue())

    def test_posix_replaces_process_instead_of_leaving_a_parent_that_swallows_sigterm(self):
        interpreter = Path('/project with spaces/.venv/bin/python')
        with patch.object(launcher.os, 'name', 'posix'), \
                patch.object(launcher.os, 'chdir') as chdir, \
                patch.object(launcher.os, 'execv') as execute, \
                patch.object(launcher.subprocess, 'Popen') as popen:
            self.assertEqual(launcher._rerun(interpreter, ['--port', '8943']), 0)
        chdir.assert_called_once_with(str(launcher.PROJECT_ROOT))
        execute.assert_called_once_with(str(interpreter), [str(interpreter), str(launcher.APP_DIR / 'run.py'), '--port', '8943'])
        popen.assert_not_called()

    def test_posix_exec_failure_reports_environment_problem(self):
        interpreter = Path('/unavailable/python')
        stderr = StringIO()
        with patch.object(launcher.os, 'name', 'posix'), \
                patch.object(launcher.os, 'chdir'), \
                patch.object(launcher.os, 'execv', side_effect=OSError('cannot execute')), \
                patch.object(launcher.subprocess, 'Popen') as popen, contextlib.redirect_stderr(stderr):
            self.assertEqual(launcher._rerun(interpreter, ['--check']), 2)
        popen.assert_not_called()
        self.assertIn('.venv', stderr.getvalue())

    def test_windows_interrupt_stops_child_if_it_did_not_receive_ctrl_c(self):
        interpreter = Path('/project/.venv/Scripts/python.exe')
        child = Mock()
        child.wait.side_effect = [KeyboardInterrupt(), None]
        child.poll.return_value = None
        with patch.object(launcher.os, 'name', 'nt'), patch.object(launcher.subprocess, 'Popen', return_value=child):
            self.assertEqual(launcher._rerun(interpreter, []), 130)
        child.terminate.assert_called_once_with()
        self.assertEqual(child.wait.call_args.kwargs, {'timeout': 5})

    def test_pdf_preflight_invokes_actual_renderer_contract_with_chinese_and_table(self):
        module = Mock()
        module.render_export_pdf.return_value = b'%PDF-1.4\npreflight'
        with patch.object(launcher.importlib, 'import_module', return_value=module) as load:
            launcher._check_pdf()
        load.assert_called_once_with('manuscript_pdf')
        sample = module.render_export_pdf.call_args.args[0]
        self.assertIn('中文', sample['text'])
        self.assertIn('| --- | --- |', sample['text'])
        self.assertEqual(sample['export']['mode'], 'review')

    def test_pdf_preflight_rejects_a_non_pdf_response(self):
        module = Mock()
        module.render_export_pdf.return_value = b'<html>error</html>'
        with patch.object(launcher.importlib, 'import_module', return_value=module):
            with self.assertRaisesRegex(ValueError, '有效文件'):
                launcher._check_pdf()

    def test_existing_environment_reexec_happens_before_dependency_check(self):
        python = Path('/project/.venv/bin/python')
        with patch.object(launcher, '_project_python', return_value=python), \
                patch.object(launcher, '_rerun', return_value=0) as rerun, \
                patch.object(launcher, '_check_pdf') as check:
            self.assertEqual(launcher.main(['--check']), 0)
        rerun.assert_called_once_with(python, ['--check'])
        check.assert_not_called()

    def test_check_only_never_starts_server(self):
        stdout = StringIO()
        with patch.object(launcher, '_project_python', return_value=None), \
                patch.object(launcher, '_check_pdf') as check, \
                patch.object(launcher.os, 'chdir'), \
                patch.object(launcher.runpy, 'run_path') as server, contextlib.redirect_stdout(stdout):
            self.assertEqual(launcher.main(['--check']), 0)
        check.assert_called_once_with()
        server.assert_not_called()
        self.assertIn('检查通过', stdout.getvalue())

    def test_missing_dependency_exits_with_same_interpreter_install_command(self):
        stderr = StringIO()
        with patch.object(launcher, '_project_python', return_value=None), \
                patch.object(launcher, '_check_pdf', side_effect=ImportError('reportlab')), \
                patch.object(launcher.os, 'chdir'), \
                patch.object(launcher.runpy, 'run_path') as server, contextlib.redirect_stderr(stderr):
            self.assertEqual(launcher.main(['--check']), 2)
        server.assert_not_called()
        self.assertIn('-m pip install -r', stderr.getvalue())
        self.assertIn(str(launcher.APP_DIR / 'requirements.txt'), stderr.getvalue())
        self.assertIn(sys.executable, stderr.getvalue())

    def test_missing_font_exits_without_starting_a_broken_service(self):
        stderr = StringIO()
        with patch.object(launcher, '_project_python', return_value=None), \
                patch.object(launcher, '_check_pdf', side_effect=ValueError('font missing')), \
                patch.object(launcher.os, 'chdir'), \
                patch.object(launcher.runpy, 'run_path') as server, contextlib.redirect_stderr(stderr):
            self.assertEqual(launcher.main([]), 2)
        server.assert_not_called()
        self.assertIn('BOOKDISTILL_PDF_FONT', stderr.getvalue())

    def test_start_uses_app_location_and_forwards_host_and_port(self):
        original_argv = sys.argv
        try:
            with patch.object(launcher, '_project_python', return_value=None), \
                    patch.object(launcher, '_check_pdf') as check, \
                    patch.object(launcher.os, 'chdir') as chdir, \
                    patch.object(launcher.runpy, 'run_path') as server:
                self.assertEqual(launcher.main(['--host', '0.0.0.0', '--port', '8943']), 0)
            check.assert_called_once_with()
            chdir.assert_called_once_with(str(launcher.PROJECT_ROOT))
            server.assert_called_once_with(str(launcher.APP_DIR / 'server.py'), run_name='__main__')
            self.assertEqual(sys.argv[1:], ['--host', '0.0.0.0', '--port', '8943'])
        finally:
            sys.argv = original_argv

    def test_windows_install_command_quotes_spaces_without_shell_interpolation(self):
        command = launcher._command(['C:/Program Files/Python/python.exe', '-m', 'pip', 'install', '-r', 'D:/My Project/app/requirements.txt'], 'nt')
        self.assertEqual(command, '"C:/Program Files/Python/python.exe" -m pip install -r "D:/My Project/app/requirements.txt"')


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Launch the web app with its project environment on Windows, macOS or Linux."""

import argparse
import importlib
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent


def _project_python(project_root=None, prefix=None, platform=None):
    """Prefer the existing venv; do not confuse its executable symlink with base Python."""
    project_root = Path(project_root or PROJECT_ROOT)
    environment = project_root / '.venv'
    prefix = Path(sys.prefix if prefix is None else prefix)
    platform = os.name if platform is None else platform
    candidate = environment / ('Scripts/python.exe' if platform == 'nt' else 'bin/python')
    if candidate.is_file() and prefix.resolve() != environment.resolve():
        return candidate
    return None


def _command(parts, platform=None):
    parts = [str(part) for part in parts]
    if (os.name if platform is None else platform) == 'nt':
        return subprocess.list2cmdline(parts)
    return ' '.join(shlex.quote(part) for part in parts)


def _check_pdf():
    """Check the same renderer and fonts used by downloads without touching project data."""
    module = importlib.import_module('manuscript_pdf')
    content = module.render_export_pdf({
        'filename': '环境检查.md',
        'text': '# 中文排版检查\n\n图书内容、植物观察与来源出处。English 123。\n\n| 内容 | 状态 |\n| --- | --- |\n| 中文字体 | 已加载 |',
        'export': {'mode': 'review', 'project_revision': 1, 'created_at': ''},
    })
    if not isinstance(content, bytes) or not content.startswith(b'%PDF-'):
        raise ValueError('PDF 排版组件没有生成有效文件。')


def _rerun(python, arguments):
    command = [str(python), str(APP_DIR / 'run.py'), *arguments]
    try:
        if os.name != 'nt':
            # Preserve the service PID so SIGTERM from a process manager reaches the server.
            os.chdir(str(PROJECT_ROOT))
            os.execv(str(python), command)
            return 0
        child = subprocess.Popen(command, cwd=str(PROJECT_ROOT))
    except OSError as error:
        print('无法使用项目的 .venv 启动：%s' % error, file=sys.stderr)
        print('请检查该虚拟环境，或按 app/README.md 为本机重新建立环境。', file=sys.stderr)
        return 2
    try:
        return child.wait()
    except KeyboardInterrupt:
        # Ctrl+C normally reaches both console processes; stop a child that did not receive it.
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        return 130


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description='启动书世界，优先使用本项目的 .venv 环境。')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址，默认仅本机')
    parser.add_argument('--port', default=8942, type=int, help='监听端口，默认 8942')
    parser.add_argument('--check', action='store_true', help='检查依赖及中文 PDF，不启动服务')
    args = parser.parse_args(arguments)
    if not 1 <= args.port <= 65535:
        parser.error('端口必须在 1 到 65535 之间')

    python = _project_python()
    if python is not None:
        return _rerun(python, arguments)
    if sys.version_info < (3, 9):
        print('需要 Python 3.9 或更新版本，请使用该版本创建项目 .venv。', file=sys.stderr)
        return 2

    # Module and asset locations are relative to this script, never the caller's working directory.
    os.chdir(str(PROJECT_ROOT))
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    try:
        _check_pdf()
    except ImportError:
        print('当前 Python 环境缺少应用依赖。请安装后重新启动：', file=sys.stderr)
        print(_command([sys.executable, '-m', 'pip', 'install', '-r', APP_DIR / 'requirements.txt']), file=sys.stderr)
        print('建议先按 app/README.md 建立项目 .venv，避免安装到全局环境。', file=sys.stderr)
        return 2
    except Exception as error:
        print('PDF 环境检查未通过：%s' % error, file=sys.stderr)
        print('请检查 app/fonts 中的随附字体；自定义字体使用 BOOKDISTILL_PDF_FONT。', file=sys.stderr)
        return 2

    if args.check:
        print('检查通过：PDF 排版组件及中文字体可用。')
        print('Python：%s' % sys.executable)
        return 0
    sys.argv = [str(APP_DIR / 'server.py'), '--host', args.host, '--port', str(args.port)]
    runpy.run_path(str(APP_DIR / 'server.py'), run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

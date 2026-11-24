"""Launch the locally installed write-xhs app from the local BookWorld workspace."""

from pathlib import Path
import subprocess
import sys


def _workspace():
    return Path.home() / 'Library' / 'Application Support' / 'BookWorld' / 'Xiaohongshu'


def _bundle():
    return _workspace() / '写点小红书文案.app'


def local_origin(handler):
    addresses = ('127.0.0.1', '::1')
    if handler.server.server_address[0] not in addresses or handler.client_address[0] not in addresses:
        return None
    host = handler.headers.get('Host', '').lower()
    port = handler.server.server_address[1]
    if host in ('localhost:%d' % port, '127.0.0.1:%d' % port, '[::1]:%d' % port):
        return 'http://' + host
    return None


def status(handler):
    if sys.platform != 'darwin' or not local_origin(handler):
        return {'available': False, 'reason': '桌面版适用于运行书世界的本机 Mac。'}
    if not (_bundle() / 'Contents' / 'MacOS' / 'BookSocialStudio').is_file():
        return {'available': False, 'reason': '本机还没有安装小红书桌面版。'}
    return {'available': True}


def launch():
    root = _workspace()
    subprocess.run([
        '/usr/bin/open', '-a', str(_bundle()),
        '--env', 'BOOKSOCIAL_QA_OUTPUT_DIR=' + str(root / '成果'),
        '--env', 'BOOKSOCIAL_QA_RECOVERY_DIR=' + str(root / '恢复记录'),
        '--env', 'BOOKSOCIAL_UPDATE_STORAGE_ROOT=' + str(root / '内容版本'),
    ], check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

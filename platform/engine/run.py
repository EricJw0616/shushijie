# -*- coding: utf-8 -*-
"""一站式入口：一本书或整库，从原始文本跑到可看的看板。

  python run.py                  # 整库全跑（判型→切段→稳定层→导出→看板）
  python run.py 朝花夕拾          # 只跑指定书（仍会重导出全库与看板）
  python run.py --check          # 只跑质检，不改产物

这就是「可持续」的全部实现：没有手工步骤，没有只在某台机器上有效的路径。
"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

STEPS = [
    ('判型+切段+稳定层', ['pipeline.py']),
    ('规则卡质检', ['rules.py']),
    ('主题卡质检+数字填充', ['topics.py']),
    ('易错对照质检', ['mirrors.py']),
    ('导出资产库', ['export.py']),
    ('生成标签库', ['taglib.py']),
    ('生成候选卡资产库页', ['cardboard.py']),
    ('生成看板', ['board.py']),
    ('生成标签数据库页', ['tagboard.py']),
]


def run(script, args=(), quiet=False):
    cmd = [PY, os.path.join(HERE, script)] + list(args)
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0 and not quiet:
        print(f'  ! {script} 返回 {r.returncode}')
        print((r.stdout or '')[-800:])
        print((r.stderr or '')[-800:])
    return r


def main():
    argv = sys.argv[1:]
    check_only = '--check' in argv
    books = [a for a in argv if not a.startswith('--')]

    print('=' * 62)
    print('图书内容提取流水线', '（只质检）' if check_only else '')
    print('=' * 62)

    for label, cmd in STEPS:
        script, args = cmd[0], cmd[1:]
        if script == 'pipeline.py':
            if check_only:
                print(f'[跳过] {label}')
                continue
            args = books
        if script == 'topics.py' and not check_only:
            args = ['ZHS', '../cards/zhaohuaxishi.topics.json']
        # --check 声明「不改产物」，那就不能重写页面。
        # 原实现只跳过 pipeline，board/tagboard 照跑，会拿旧的 catalog 重写两个
        # HTML —— 既改动了产物，又和「只质检」的字面承诺不符。
        if check_only and script in ('board.py', 'tagboard.py', 'cardboard.py'):
            print(f'[跳过] {label}（--check 不改产物）')
            continue
        print(f'\n>>> {label}')
        r = run(script, args)
        # 打印关键几行
        for line in (r.stdout or '').strip().split('\n')[-6:]:
            if line.strip():
                print('   ', line)
        # 任何一步失败都必须停：旧实现会带着半套产物继续跑 export/board，
        # 页面看起来「跑完了」，实际拿的是上一次的 catalog。
        if r.returncode != 0:
            print(f'\n[中止] {label} 失败（返回 {r.returncode}），后续步骤未执行。')
            return r.returncode

    if check_only:
        print('\n' + '=' * 62)
        print('质检完成。--check 模式未改动任何产物与页面。')
        print('=' * 62)
        return

    print('\n' + '=' * 62)
    print('完成。三个页面：')
    print('  论证页    platform/书库平台看板.html')
    print('  数据库    platform/图书标签数据库.html')
    print('  候选卡库  platform/候选卡资产库.html')
    print('=' * 62)


if __name__ == '__main__':
    sys.exit(main() or 0)
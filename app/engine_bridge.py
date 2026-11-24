# -*- coding: utf-8 -*-
"""App 与解析引擎之间的桥。

只做四件事：
  1. 把项目路径统一到 BOOKDISTILL_ROOT（换机 / 上服务器不改代码）
  2. 读/写「解析能力」配置（platform/config/capabilities.json）
  3. 以子进程方式调引擎脚本，返回可读日志
  4. 给后台页面提供默认能力矩阵、阈值、精度分级

注意：这里没有 SQLite。所有业务数据走 app/data 下的 JSON/JSONL，
后续换 PostgreSQL 只需要换 storage adapter，业务代码不动。
"""
import datetime
import io
import json
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('BOOKDISTILL_ROOT') or os.path.dirname(APP_DIR)

PLATFORM = os.path.join(ROOT, 'platform')
ENGINE = os.path.join(PLATFORM, 'engine')
OUT = os.path.join(PLATFORM, 'out')
LIB = os.path.join(PLATFORM, 'library')
RAW = os.path.join(ROOT, '书库分类', 'raw')
TRASH_DIR = os.path.join(ROOT, '书库分类', '退库')
CONFIG_DIR = os.path.join(PLATFORM, 'config')
CAPS = os.path.join(CONFIG_DIR, 'capabilities.json')
HTML_BOARD = os.path.join(PLATFORM, '书库平台看板.html')
HTML_TAGDB = os.path.join(PLATFORM, '图书标签数据库.html')
HTML_CARDS = os.path.join(PLATFORM, '候选卡资产库.html')

if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

# cards.py 在 import 时读一次配置。为了后台改完立刻可见，这里每次调用
# load_plan() 重新读文件，而不是只读模块级 PLAN。
import cards as CD  # noqa: E402

PROTO_NAMES = {
    'P1': '规范型', 'P2': '知识型', 'P3': '论说型', 'P4': '叙事型',
    'P5': '戏曲型', 'P6': '散文型', 'P7': '韵文集型', 'P8': '条目型',
    'P9': '选集笺注型', 'P10': '笔记志书型', 'P11': '图鉴型', 'P12': '纪事型',
}
PROTO_ORDER = list(PROTO_NAMES)


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path, default=None):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return default if default is not None else {}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = __import__('tempfile').mkstemp(dir=os.path.dirname(path),
                                             prefix='.tmp-')
    with os.fdopen(fd, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def default_plan():
    """引擎默认的「原型 → 抽取器」表，只取标签名。"""
    return {p: [label for label, _ in items]
            for p, items in CD.DEFAULT_PLAN.items()}


def current_plan():
    """当前生效配置；没有配置文件时就是默认值。"""
    plan = CD.load_plan()
    return {p: [label for label, _ in items] for p, items in plan.items()}


def all_labels():
    return list(CD.ALL_LABELS)


def content_labels():
    return [label for label in all_labels() if label in CD.enabled_labels(CAPS)]


def save_content_labels(labels):
    if not isinstance(labels, list) or any(not isinstance(label, str) or label not in CD.ALL_LABELS for label in labels):
        raise ValueError('请从列表选择要检查的内容')
    payload = read_caps()
    enabled = set(labels)
    payload.update({'version': 1, 'updated_at': now(), 'content_labels': [label for label in all_labels() if label in enabled],
                    'note': '按实际内容检查标签。设置对之后新导入和重新处理的书生效。'})
    write_json(CAPS, payload)
    return payload


def confirm_info():
    """每种候选的精度分级说明（给后台矩阵做 tooltip）。"""
    return {k: {'精度': v[0], '资产性质': v[1], '说明': v[2]}
            for k, v in CD.CONFIRM.items()}


def read_caps():
    return read_json(CAPS, {}) or {}


def save_plan(plan):
    """校验并落盘。只影响之后新跑/重跑的书，历史产物不会自动变。"""
    valid = set(CD.ALL_LABELS)
    default = default_plan()
    clean = {}
    for proto in PROTO_ORDER:
        labels = plan.get(proto, default.get(proto, []))
        if not isinstance(labels, list):
            raise ValueError(f'{proto} 的抽取器列表必须是数组')
        seen, out = set(), []
        for label in labels:
            if label not in valid:
                raise ValueError(f'未知抽取器：{label}')
            if label not in seen:
                seen.add(label)
                out.append(label)
        clean[proto] = out
    payload = {
        'version': 1,
        'updated_at': now(),
        'note': '旧设置中被所有类型关闭的检查项仍保持关闭。设置对之后处理的书生效。',
        'plan': clean,
    }
    write_json(CAPS, payload)
    return payload


def reset_plan():
    payload = {
        'version': 1,
        'updated_at': now(),
        'note': '恢复默认：所有内容检查项都已开启。',
        'plan': default_plan(),
    }
    write_json(CAPS, payload)
    return payload


def thresholds():
    """只读展示。判型阈值不开放后台改：单本书调阈值会让全库口径失真。"""
    import measure as M
    return {
        'MIN_HAN': M.MIN_HAN,
        'MIN_HAN_RATIO': M.MIN_HAN_RATIO,
        'MAX_SAVG': M.MAX_SAVG,
        '图谱强证据人物': 6,
        '图谱场景密度': 0.38,
        '切段保留率下限': 95,
        '说明': ('阈值由全库实测倒推，不随单本书调整；'
                 '后台只开放「每类书启用哪些抽取器」，阈值改动须走代码 + 全库回归。'),
    }


def run_script(script, args=None, timeout=1200, env_extra=None):
    """跑一个引擎脚本，返回 (returncode, stdout, stderr)。"""
    args = list(args or [])
    cmd = [sys.executable, os.path.join(ENGINE, script)] + args
    env = os.environ.copy()
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.run(cmd, cwd=ENGINE, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout,
                           env=env)
        return p.returncode, p.stdout or '', p.stderr or ''
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or ''), f'超时（>{timeout}s）'
    except Exception as e:
        return 1, '', f'{type(e).__name__}: {e}'


def rebuild_assets(skip_pages=False, include_checks=True):
    """删书 / 改判后重建汇总库与页面。返回 [(脚本, 返回码)]。

    删书时 include_checks=False：rules/topics/mirrors 检的是人工确认卡，
    与被删的书无关；若删的正好是朝花夕拾，topics.py 会因缺卡而失败，
    进而把 export/taglib 也卡住，导致书库索引和页面停在删前状态。
    """
    steps = []
    if include_checks:
        steps += [('rules.py', []),
                  ('topics.py', ['ZHS', '../cards/zhaohuaxishi.topics.json']),
                  ('mirrors.py', [])]
    steps += [('export.py', []),
              ('taglib.py', [])]
    if not skip_pages:
        steps += [('cardboard.py', []), ('board.py', []), ('tagboard.py', [])]
    results = []
    for script, args in steps:
        rc, out, err = run_script(script, args)
        results.append({'script': script, 'returncode': rc,
                        'stdout': out[-2000:], 'stderr': err[-2000:]})
        if rc != 0:
            break
    return results


def book_json(code):
    return read_json(os.path.join(OUT, code, 'book.json'), {}) or {}


def books_json():
    return read_json(os.path.join(OUT, 'books.json'), []) or []


def catalog_json():
    return read_json(os.path.join(LIB, 'catalog.json'), []) or []


def tags_json():
    return read_json(os.path.join(LIB, 'tags.json'), {}) or {}

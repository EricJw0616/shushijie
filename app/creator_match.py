"""Match a book with creator works, then look up the accounts for those works."""

import gzip
import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parent / 'resources' / 'creator_match.jsonl.gz'
DOMAINS = frozenset(('文学阅读', '教育学习', '童书教育', '生活科普', '商业财经', '心灵成长'))
_LOAD_LOCK = threading.Lock()


@dataclass(frozen=True)
class Creator:
    row: int
    handle: str
    name: str
    categories: tuple
    domain: str


class CreatorDataUnavailable(Exception):
    """The local snapshot is unavailable or unreadable."""


@lru_cache(maxsize=1)
def _read_snapshot(path, modified_ns):
    with gzip.open(path, 'rt', encoding='utf-8') as source:
        metadata = json.loads(next(source))
        creators = []
        for line in source:
            row, handle, name, categories, domain, _ = json.loads(line)
            creators.append(Creator(row, handle, name, tuple(categories), domain))
    if not creators:
        raise ValueError('达人快照没有记录')
    return tuple(creators), {**metadata, 'records': len(creators)}


def _snapshot():
    try:
        with _LOAD_LOCK:
            return _read_snapshot(SNAPSHOT, SNAPSHOT.stat().st_mtime_ns)
    except (OSError, ValueError, TypeError, StopIteration, EOFError) as error:
        raise CreatorDataUnavailable('本地达人库不可用，请检查已导入的达人数据。') from error


def known_handle(handle):
    creators, _ = _snapshot()
    return any(creator.handle == handle for creator in creators)


def _field(body, key, limit):
    value = body.get(key, '')
    if not isinstance(value, str):
        raise ValueError('书名、简介、目标读者和合作目标应为文字。')
    return value.strip()[:limit]


def _work_evidence(title, synopsis, audience, goal, only_handle=None, works=None):
    if not synopsis:
        return {}, 'missing_synopsis', '补充图书简介或书中片段，即可对照博主作品。'
    import creator_works
    from creator_content_match import ContentAnalysisUnavailable, compare

    try:
        if works is None:
            works = creator_works.read_works()
    except creator_works.WorksUnavailable:
        return {}, 'works_unavailable', '作品资料暂时无法读取。请稍后重试。'
    if not works or (only_handle is not None and not works.get(only_handle)):
        return {}, 'no_works', '暂无可评估的作品资料。可自动查找公开作品，或手动补充作品。'
    try:
        matched = compare(title, synopsis, audience, '带货成交' if goal == 'sales' else '内容种草',
                          works, only_handle=only_handle)
    except ContentAnalysisUnavailable:
        return {}, 'analysis_unavailable', '作品分析暂时不可用。请稍后重新匹配。'
    if not matched:
        return {}, 'no_match', '已收录的作品中暂未找到与本书有关的内容证据。可自动查找公开作品，或手动补充作品。'
    return matched, 'matched', ''


def _work_result(creator, evidence, goal):
    checks = ['核对原作品及内容切入点，确认表达方式和可用素材。']
    if goal == 'sales':
        checks.append('单独核对挂车、成交记录、报价、佣金和档期。')
    else:
        checks.append('确认目标受众、排期及书页或引文的使用许可。')
    return {
        'handle': creator.handle,
        'name': creator.name,
        'domains': [creator.domain] if creator.domain in DOMAINS else [],
        'product_categories': list(creator.categories),
        'tier': 'content',
        'reasons': [],
        'checks': checks,
        'angle': evidence['angle'],
        'content_match': evidence,
        'source_row': creator.row,
        **{key: evidence[key] for key in ('score', 'score_state', 'score_details', 'score_reason', 'recommend_backup')},
    }


def match(body, *, works=None, only_handle=None):
    if not isinstance(body, dict):
        raise ValueError('请输入有效的图书信息。')
    title = _field(body, 'title', 200)
    synopsis = _field(body, 'synopsis', 5000)
    audience = _field(body, 'audience', 500)
    goal = _field(body, 'goal', 20) or 'content'
    if not (title or synopsis):
        raise ValueError('请输入书名或简介。')
    if goal not in ('content', 'sales'):
        raise ValueError('合作目标应为内容合作或销售带货。')

    work_evidence, status, notice = _work_evidence(title, synopsis, audience, goal, only_handle, works)
    matches, source = [], None
    if work_evidence:
        creators, source = _snapshot()
        work_creators = {creator.handle: creator for creator in creators if creator.handle in work_evidence}
        matches = [_work_result(work_creators[handle], evidence, goal)
                   for handle, evidence in work_evidence.items() if handle in work_creators][:12]
        if not matches:
            status = 'no_match'
            notice = '找到了相关作品，暂未能在达人库核对其账号。可重新查找公开作品。'
    return {'matches': matches, 'book_topics': [], 'goal': goal,
            **({'source': source} if source is not None else {}),
            'content_status': status, 'content_notice': notice, 'summary': notice}

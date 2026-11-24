# -*- coding: utf-8 -*-
"""Per-book status for the publishing label catalogue."""
from collections import Counter


CATALOGUE = (
    ('内容和名称', (
        '定义', '枚举', '规则', '凡式', '情节', '篇目', '引书', '曲牌科介',
        '作品', '释义', '训释', '地形', '条目', '物种条目', '地名', '机构',
        '器物', '动物', '植物', '人物',
    )),
    ('出版信息', (
        '正题名', '副题名', '并列题名', '原作名', '丛书名', '卷次', '版次', '印次',
        '著者', '其他著者', '编委会', '译者', '绘者／插图', '责任编辑', '责任校对',
        '美术／封面设计', '出版社', '出版地', '出版年月', 'ISBN', 'CIP 核字号',
        '开本', '装帧', '页数', '印张', '字数', '定价', '语种', '册数', '印刷厂',
        '中图法分类号', '主题词', '内容简介', '卖点', '作者简介', '获奖记录', '推荐语',
    )),
    ('内容归纳', (
        '金句', '议题', '章节摘要', '论点', '人物关系', '难度', '读者对象', '核心概念', '关键事实',
    )),
    ('营销参考', ('场景', '时令', '地域', '事件', '竞品', '一句话卖点', '短文案金句卡')),
)

_PUBLICATION_KEYS = {
    '正题名': 'book_title', '副题名': 'subtitle', '丛书名': 'series', '版次': 'edition',
    '印次': 'impression', '著者': 'author', '译者': 'translators', '责任编辑': 'editor_in_charge',
    '出版社': 'publisher', '出版年月': 'publication_date', 'ISBN': 'isbn', 'CIP 核字号': 'cip_number',
    '开本': 'book_format', '装帧': 'binding', '页数': 'pages', '字数': 'word_count', '定价': 'price',
    '中图法分类号': 'classification', '作者简介': 'author_bio',
}
_ENTITY_KEYS = {
    '地名': ('country', 'province', 'region', 'city', 'district', 'landmark', 'nature', 'place'),
    '机构': ('org',), '器物': ('object',), '动物': ('animal',), '植物': ('plant',),
}


def for_book(detail):
    """Separate missing evidence, unfinished work, and unavailable extractors."""
    observations = {}

    def set_item(label, status, count=0, note=''):
        observations[label] = {'label': label, 'status': status, 'count': int(count or 0), 'note': note}

    book = detail['book']
    for label, result in (book.get('内容检查') or {}).items():
        state = {
            'extracted': 'available', 'not_found': 'not_found', 'needs_review': 'review',
            'disabled': 'not_run', 'failed': 'blocked', 'unsupported': 'unsupported',
        }.get(result.get('status'), 'review')
        set_item(label, state, result.get('count'), result.get('reason') or '')

    publication = (detail.get('publication') or {}).get('items') or {}
    for label, key in _PUBLICATION_KEYS.items():
        value = publication.get(key)
        if not value:
            set_item(label, 'not_run', note='尚无本书的出版信息记录。')
            continue
        status = value.get('status')
        if status == 'found':
            set_item(label, 'review' if value.get('method') == 'import' else 'available', 1)
        elif status == 'needs_review':
            set_item(label, 'review', bool(value.get('value')), '请对照版权页。')
        else:
            set_item(label, 'not_applicable' if status == 'not_applicable' else 'not_found')

    cip = detail.get('cip') or {}
    for label, key in {'出版地': '出版地', '印张': '印张', '语种': '语种'}.items():
        if cip.get(key):
            set_item(label, 'available', 1)
    for label in ('获奖记录', '竞品'):
        set_item(label, 'unsupported', note='这项需要另外提供可核实的来源。')

    names = detail.get('entity_counts') or {}
    name_states = detail.get('name_processing') or {}
    for label, keys in _ENTITY_KEYS.items():
        count = sum(int(names.get(key) or 0) for key in keys)
        if name_states.get('status') == 'blocked':
            skipped = name_states.get('refused_segments') or 0
            set_item(label, 'review', count, f'有 {skipped} 段没能自动整理名称，可直接核对原文。')
            observations[label]['anchor'] = name_states.get('refused_anchor') or ''
        elif name_states.get('status') in ('partial', 'failed', 'stale'):
            set_item(label, 'blocked', count, '部分原文尚未核对，可继续补查。')
        elif count:
            set_item(label, 'review', count, '抽到的名称可回原文核对。')
        elif name_states.get('unreadable_segments'):
            set_item(label, 'review', note='已查可读正文，部分原文需要先核对。')
        elif name_states.get('status') == 'done':
            set_item(label, 'not_found')
        else:
            set_item(label, 'not_run')
    people = max(int(names.get('person') or 0), int((detail.get('people') or {}).get('count') or 0))
    if people and not observations.get('人物', {}).get('count'):
        set_item('人物', 'review', people, '已有人物索引，可回原文核对。')

    reading = detail.get('understanding') or {}
    processing = reading.get('processing') or {}
    for label, key in {'金句': 'quotes', '议题': 'themes', '章节摘要': 'summaries'}.items():
        count = len(reading.get(key) or [])
        attempt = processing.get(key) or {}
        if attempt.get('status') in ('failed', 'partial', 'stale') or attempt.get('source_stale'):
            set_item(label, 'blocked', count, '本次有内容尚未处理，请查看原文或任务记录。')
        elif count:
            set_item(label, 'review', count, '使用前请核对原文。')
        elif key in reading:
            set_item(label, 'not_found')
        else:
            note = '可在图书的「内容成果」里生成章节摘要。' if key == 'summaries' else ''
            set_item(label, 'not_run', note=note)

    marketing = (detail.get('marketing') or {}).get('items') or {}
    for label, key in {'内容简介': 'summary', '读者对象': 'audience', '场景': 'scenarios'}.items():
        values = marketing.get(key, {}).get('value')
        if values:
            set_item(label, 'review', len(values) if isinstance(values, list) else 1, '这是根据书中内容整理的参考。')
        else:
            set_item(label, 'not_run')
    deep = (detail.get('deep') or {}).get('items') or {}
    for label, key in {'核心概念': 'concepts', '关键事实': 'facts'}.items():
        values = deep.get(key, {}).get('value')
        set_item(label, 'review' if values else 'not_run', len(values) if isinstance(values, list) else bool(values))

    groups = []
    counts = Counter()
    for group, labels in CATALOGUE:
        items = []
        for label in labels:
            if label not in observations:
                state = 'not_run' if group == '内容和名称' else 'unsupported'
                note = '这本书尚无逐项检查记录。' if state == 'not_run' else '目前没有这项的单独结果。'
                set_item(label, state, note=note)
            items.append(observations[label])
            counts[observations[label]['status']] += 1
        groups.append({'name': group, 'items': items})
    return {'groups': groups, 'counts': dict(counts), 'total': sum(counts.values())}

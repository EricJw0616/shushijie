"""Marketing task definitions shared by persistence, generation and delivery."""

TASKS = {'general': '常规营销／新书支持', 'reposition': '老书新卖点',
         'theme': '跨书主题营销', 'channel': '渠道素材包'}
CHANNELS = ('公众号', '小红书', '短视频', '达人讲书', '书店活动')


def normalize(value):
    task = value.get('marketing_task', 'general')
    if not isinstance(task, str) or task not in TASKS:
        raise ValueError('营销任务类型无效')
    result = {'marketing_task': task}
    for key, label, maximum in [('target_codes', '推广图书', 12), ('channels', '制作渠道', 5)]:
        items = value.get(key, [])
        if not isinstance(items, list) or any(not isinstance(x, str) or not x.strip() for x in items):
            raise ValueError(label + '应为选项列表')
        items = list(dict.fromkeys(x.strip() for x in items))
        if len(items) > maximum:
            raise ValueError(label + '超出单次任务范围，请拆分任务')
        if key == 'channels' and any(x not in CHANNELS for x in items):
            raise ValueError('制作渠道无效')
        result[key] = items
    return result


def context(brief, library, require_complete=True):
    config = normalize(brief)
    task = config['marketing_task']
    targets = config['target_codes'] if task in ('theme', 'channel') else ([brief['source_code']] if brief.get('source_code') else [])
    if any(code not in library for code in targets):
        raise ValueError('推广图书不在当前书库，请重新选择')
    if require_complete:
        if task == 'theme' and len(targets) < 2:
            raise ValueError('跨书主题营销请至少选择两本推广图书')
        if task in ('reposition', 'channel') and not targets:
            raise ValueError('请先选择推广图书')
        if task == 'channel' and not config['channels']:
            raise ValueError('渠道素材包请至少选择一个制作渠道')
        if task == 'general' and not targets and not str(brief.get('new_book_brief') or '').strip():
            raise ValueError('新书营销需要填写已确认的新书资料；也可先选择推广图书')
    return {**config, 'target_books': [{'code': code, 'book': library[code].get('book') or code} for code in targets]}


def require_evidence(config, materials):
    present = {m['code'] for m in materials}
    missing = [b['book'] for b in config['target_books'] if b['code'] not in present]
    if missing:
        raise ValueError('请为每本推广图书采用至少一条自身的有效材料：' + '、'.join(missing))

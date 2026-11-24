"""Reusable text-only delivery contracts for social notes and spoken book talks."""
import re

import marketing_context

VERSION = '1.0'
CHANNELS = ('小红书', '达人讲书')


def _text(value, label, limit=1600, optional=False):
    if optional and value in (None, ''):
        return ''
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError('%s应为%s%d字以内的文字。' % (label, '非空、' if not optional else '', limit))
    return value.strip()


def _refs(value, allowed):
    if not isinstance(value, list) or any(not isinstance(x, str) or x not in allowed for x in value):
        raise ValueError('渠道制作内容引用了未提供的材料。')
    return list(dict.fromkeys(value))


def booktalk_capacity(brief):
    return marketing_context.narration_capacity(brief, default_seconds=240, minimum_seconds=30,
                                               maximum_seconds=1800, channel_label='讲书')


def _roles(snapshot):
    brief = snapshot.get('brief') or {}
    roles = (snapshot.get('marketing_context') or {}).get('roles') or {}
    return {'audience': roles.get('viewer') or brief.get('audience') or '本次内容的读者',
            'book_readers': roles.get('book_readers') or brief.get('book_readers') or '',
            'decision_maker': (roles.get('decision_maker') or brief.get('decision_maker') or '')
                if brief.get('purpose') == 'purchase' else ''}


def image_prompt(pack, card):
    def sentence(label, value):
        return label + '：' + value.strip().rstrip('。！？!?；;') + '。'

    parts = ['制作小红书%s。' % ('封面图' if card['role'] == 'cover' else '图文卡'),
             sentence('最终观众', pack['audience'])]
    if pack['book_readers'] and pack['book_readers'] != pack['audience']:
        parts.append(sentence('本书阅读者', pack['book_readers']))
    if pack['decision_maker'] and pack['decision_maker'] not in pack['audience']:
        parts.append(sentence('本次选书决策者', pack['decision_maker']))
    parts += [sentence('本张用途', card['purpose']), sentence('主体', card['subject']),
              sentence('整组视觉风格', pack['visual_style']), sentence('画幅', pack['aspect_ratio']),
              sentence('构图', card['composition']), sentence('画面要求', card['scene_prompt']),
              '画面不渲染文字，标题与说明在排版时添加。']
    if card['overlay_text']:
        parts.append('为后期文字“%s”留出清楚的排版区域。' % card['overlay_text'])
    if card['reference_type'] != 'none':
        parts.append(sentence('在生图工具中上传对应参考图', card['reference_requirement']))
        if card['reference_type'] in ('book_cover', 'book_page'):
            parts.append('书封或内页采用提供的真实图片，保留原有文字与版式，不重新生成或伪造。')
        else:
            parts.append('准确对象或真实人物按对应参考保持特征，不用想象代替身份或形态。')
    else:
        parts.append('用概念示意表达没有参考图的实物和场景，避免画成真实标本、人物肖像、历史现场、书封或书页。')
    return re.sub(r'\s+', ' ', ''.join(parts)).strip()


def validate(channel, value, snapshot, allowed):
    if not isinstance(value, dict):
        raise ValueError('%s缺少完整交付内容。' % channel)
    roles = _roles(snapshot)
    if channel == '小红书':
        pack = {'type': 'social_note', **roles,
                'note_body': _text(value.get('note_body'), '发布正文', 5000),
                'ending': _text(value.get('ending'), '笔记结尾', 500, optional=True),
                'visual_style': _text(value.get('visual_style'), '整组视觉风格', 900),
                'aspect_ratio': _text(value.get('aspect_ratio'), '图文画幅', 12), 'cards': []}
        if not re.fullmatch(r'\d{1,2}:\d{1,2}', pack['aspect_ratio']) or not all(int(n) > 0 for n in pack['aspect_ratio'].split(':')):
            raise ValueError('图文画幅应为有效比例，例如3:4。')
        cards = value.get('cards')
        if not isinstance(cards, list) or not 2 <= len(cards) <= 10:
            raise ValueError('小红书应包含1张封面和1至9张有具体内容的图文卡。')
        for index, row in enumerate(cards, 1):
            role = 'cover' if index == 1 else 'content'
            if not isinstance(row, dict) or row.get('role') != role:
                raise ValueError('第1张应为封面，其余应为图文卡。')
            card = {'number': index, 'role': role,
                    **{key: _text(row.get(key), '第%d张%s' % (index, label), limit) for key, label, limit in (
                        ('title', '标题', 120), ('purpose', '用途', 500), ('subject', '主体', 700),
                        ('composition', '构图', 900), ('scene_prompt', '画面要求', 1800))},
                    'overlay_text': _text(row.get('overlay_text'), '后期文字', 600, optional=True),
                    'reference_type': row.get('reference_type', 'none'),
                    'reference_requirement': _text(row.get('reference_requirement'), '参考图要求', 1200, optional=True),
                    'asset_ids': _refs(row.get('asset_ids'), allowed)}
            if card['reference_type'] not in ('none', 'book_cover', 'book_page', 'accurate_object', 'real_person', 'other'):
                raise ValueError('配图参考类型无效。')
            if bool(card['reference_requirement']) != (card['reference_type'] != 'none'):
                raise ValueError('只为确实需要准确参考的画面填写对应参考图要求。')
            card['prompt'] = image_prompt(pack, card)
            pack['cards'].append(card)
        return pack
    if channel == '达人讲书':
        budget = snapshot.get('booktalk_capacity') or booktalk_capacity(snapshot.get('brief') or {})
        duration = value.get('duration_seconds')
        if type(duration) is not int or duration != budget['duration_seconds']:
            raise ValueError('讲书计划时长应保持为%d秒。' % budget['duration_seconds'])
        rows = value.get('sections')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 30:
            raise ValueError('讲书稿应按实际内容安排1至30个完整讲述段落。')
        sections = []
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError('讲述段落格式无效。')
            section = {'number': i, 'heading': _text(row.get('heading'), '段落标题', 120),
                       'script': _text(row.get('script'), '完整讲述正文', 6000),
                       'cue': _text(row.get('cue'), '提词', 700, optional=True),
                       'page_hint': _text(row.get('page_hint'), '翻页提示', 700, optional=True),
                       'asset_ids': _refs(row.get('asset_ids'), allowed)}
            # Extracted anchors are not reader-facing printed page numbers.
            if re.search(r'(?:第\s*)?\d+\s*页|[Pp][.．]\s*\d+', section['page_hint']):
                raise ValueError('翻页提示请用已提供的章节或内容定位，不补造书页页码。')
            sections.append(section)
        count = sum(c.isalnum() for s in sections for c in s['script'])
        if count > budget['limit']:
            raise ValueError('讲述正文共%d字，%d秒编辑预算上限%d字；删减旁支或重复，保留完整解释，不延长用户时长。' %
                             (count, duration, budget['limit']))
        return {'type': 'booktalk', 'operator': '讲书者', **roles, 'duration_seconds': duration,
                'narration_characters': count, 'sections': sections}
    raise ValueError('不支持的渠道交付类型。')


def asset_ids(pack):
    return list(dict.fromkeys(aid for item in pack.get('cards', pack.get('sections', [])) for aid in item['asset_ids']))


def render(pack):
    if pack['type'] == 'social_note':
        lines = ['#### 发布正文', '', pack['note_body'], '']
        if pack['ending']:
            lines += [pack['ending'], '']
        lines += ['#### 配图制作', '']
        for card in pack['cards']:
            lines += ['##### 第 %d 张 · %s · %s' % (card['number'], '封面' if card['role'] == 'cover' else '图文卡', card['title']), '']
            if card['overlay_text']:
                lines += ['**后期文字：** ' + card['overlay_text'], '']
            if card['reference_requirement']:
                lines += ['**参考图：** ' + card['reference_requirement'], '']
            lines += ['**生图提示词**', '', card['prompt'], '']
        return '\n'.join(lines).strip()
    lines = ['#### 讲述正文', '']
    for section in pack['sections']:
        lines += ['**%s**' % section['heading'], '', section['script'], '']
    lines += ['#### 提词与翻页', '', '计划讲述时长：%g 分钟。' % (pack['duration_seconds'] / 60), '']
    for section in pack['sections']:
        if not section['cue'] and not section['page_hint']:
            continue
        lines += ['##### 第 %d 段 · %s' % (section['number'], section['heading']), '']
        if section['cue']:
            lines += ['**提词：** ' + section['cue'], '']
        if section['page_hint']:
            lines += ['**翻页：** ' + section['page_hint'], '']
    return '\n'.join(lines).strip()


def instruction(channels):
    text = ''
    if '小红书' in channels:
        text += ('小红书必须交付完整发布笔记和按张可复制的生图提示词，仅文字，不生成媒体。'
                 '该channel_assets项body和cta置空，增加delivery对象：'
                 '{"note_body":"完整发布正文","ending":"自然结尾，可空","visual_style":"统一具体风格",'
                 '"aspect_ratio":"3:4","cards":[{"role":"cover或content","title":"本张名",'
                 '"purpose":"本张让观众知道什么","subject":"实际主体","composition":"具体构图与留白",'
                 '"scene_prompt":"可交给生图工具的具体画面描述","overlay_text":"后期添加的本张文案，可空",'
                 '"reference_type":"none或book_cover或book_page或accurate_object或real_person或other",'
                 '"reference_requirement":"对应准确参考图要求，无需时空字符串","asset_ids":["本次材料ID"]}]}。'
                 '第1张是cover，其余1至9张content；数量由实际内容决定，不用重复文案凑页。'
                 '发布正文不含制作过程、提示词、参考图操作或内部审核提醒；每张图有明确内容增量，不能只用漂亮背景代替图文信息。'
                 '每张具体图解、书中对象或观点的asset_ids对应来源；纯构图设计可为空，不能捏造事实。'
                 '封面可以是观点或故事视觉，不必展示真实书封；普通图形、留白、纹理不得强制用户准备参考图。'
                 '确实展示书封/内页时使用真实图片，不重新生成封面、书页文字或假书评。'
                 '需要辨认的真实人物、物种、标本或具体实物必须使用相应参考类型。没有参考时改用明确的概念示意，'
                 '画面描述中只给符号、线条和关系，不把它说成真实标本、历史现场或原书插图。'
                 '用途只写这一张传达什么，构图只写主体位置、视线与留白，画面要求写可见细节，避免重复。'
                 '所有画面文字后期排版；scene_prompt讲清主体、关系、配色、构图，不写“自行设计”等空话。')
    if '达人讲书' in channels:
        text += ('达人讲书交付给讲书者使用，audience是实际听众，不是稿件使用者；图书读者与购买决策者继续按明确任务区分。'
                 '必须提供可直接讲述的完整稿，不以主题提纲或卖点清单充数。'
                 '该channel_assets项body和cta置空，增加delivery对象：'
                 '{"duration_seconds":240,"sections":[{"heading":"段落标题","script":"完整可讲正文",'
                 '"cue":"必要提词或停顿提示，无需时为空","page_hint":"按已提供章节或内容定位的翻页提示，无需时为空",'
                 '"asset_ids":["本次材料ID"]}]}。'
                 'duration_seconds使用project.booktalk_capacity固定的任务时长，240只是示例。'
                 '正文篇幅按其中target_characters组织、limit为上限；计划时长是编写安排，不代表实测配音。'
                 '围绕听众当下关心的一件事确定讲述主线。选原书中能支撑它的具体段落，让听众先听到一个动作、冲突、困惑或观点，再听到为什么这一段值得读。'
                 '讲出书怎样呈现这个人或问题，例如作者用了什么细节让人理解处境，或两段内容放在一起能看见什么；区分原书写到的事实和讲书者提供的读法。'
                 '把这种解读落到听众能带走的感受、理解或选书判断。可根据场景给一个具体试读入口，说明适合哪类阅读期待；不把受众的反应写成既定结果。'
                 '时长较长时增加具体片段、解读层次和听众判断的依据，优先使用同一主线的不同书中细节。不要慢读短稿、重复总结、泛讲励志、罗列章节或补编内容来凑时长。'
                 '来源单薄到无法完成这次解读时，在writing_needs指出真正该补的片段。材料支持的解释和可用稿件仍应交付。'
                 '工作区的核对理由和写作限制不进入口播或试讲提示。比如两段读法各自有依据时，用“书里还写了另一段”自然转场，无需口头声明两段之间的证据关系。'
                 '提词/翻页信息与实际讲稿分开，不把操作说明念进正文。翻页仅按已提供章节或内容定位，不编页码。'
                 '不冒充讲书者已买书、读完、亲测或收到读者反馈；不编造体验、报价、合作费用、优惠、销量、评价或效果承诺。'
                 '第一人称可用于当前讲述动作如“我们来看”，不能伪造个人经历；不必强行安排交易结尾。')
    return text

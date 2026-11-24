# -*- coding: utf-8 -*-
"""判定层：逐列判断「这本书里有没有这类内容」。

输出落在 out/<code>/judge.json，供抽取层决定跑哪些列。
不调模型时不动任何产物；调失败也不阻塞入库。

用法：
    python3 judge.py B60            # 单本
    python3 judge.py B56 B58 B59 B60
"""
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P          # noqa: E402
import llm                 # noqa: E402

OUT = P.OUT
PROMPT_VERSION = 'judge-v1'

COLUMNS = [
    ('定义', '对概念或术语作解释，如「X 是指…」「所谓 X…」'),
    ('枚举', '并列列举一份清单，如「一曰…二曰…」「分为三类」'),
    ('规则', '提出要求、禁令或条件—动作，如「必须」「不得」「应当」'),
    ('凡式', '以「凡…者…」给出通则'),
    ('情节', '叙述事件推进：谁做了什么、结果如何'),
    ('篇目', '有篇/章/回/卷的标题结构'),
    ('引书', '引用其他书籍，形如《书名》'),
    ('曲牌科介', '戏曲的曲牌名与舞台提示，常用【】标出'),
    ('作品', '列举作品名（诗、画、曲目等）'),
    ('释义', '解释词义或句意'),
    ('训释', '训诂体例，如「X，Y 也」'),
    ('地形', '地理志体例，如「又东三百里，曰某山」'),
    ('条目', '有固定小标题的条目体（志书、图谱、辞书）'),
    ('物种条目', '图鉴式物种档案：中名 + 学名 + 字段（来源/生境/分布）'),
]

SYS = (
    '你是图书结构分析员。判断这本书里是否真实存在下列各类内容。'
    '只根据给出的信息判断，不要推测；拿不准就判 false。'
    '输出严格 JSON，不要解释、不要代码块。'
)


def fingerprint(code):
    rows = [json.loads(l) for l in io.open(os.path.join(OUT, code, 'segments.jsonl'), encoding='utf-8') if l.strip()]
    book = json.load(io.open(os.path.join(OUT, code, 'book.json'), encoding='utf-8'))
    outline = []
    op = os.path.join(OUT, code, 'outline.jsonl')
    if os.path.exists(op):
        outline = [json.loads(l) for l in io.open(op, encoding='utf-8') if l.strip()]
    txt = '\n'.join((r.get('文本') or '') for r in rows)
    han = len(re.findall(r'[\u4e00-\u9fff]', txt)) or 1
    quotes = sum(len(q) for q in re.findall(r'[“"]([^”"]{4,})[”"]', txt))
    sents = [s for s in re.split(r'[。！？]', txt) if len(s) > 3]
    avg = sum(len(s) for s in sents) / max(len(sents), 1)

    # 抽样：开头、中间、对白最多的一段
    picks = []
    if rows:
        picks.append(rows[0])
        picks.append(rows[len(rows) // 2])
        best = max(rows[:200], key=lambda r: (r.get('文本') or '').count('“') + (r.get('文本') or '').count('"'))
        if best.get('id') not in [p.get('id') for p in picks]:
            picks.append(best)

    return {
        'book': book, 'rows': rows, 'outline': outline, 'picks': picks,
        'stats': {'段数': len(rows), '篇数': len(outline),
                  '对白率': round(quotes / han, 3), '平均句长': round(avg, 1)},
    }


def build_prompt(fp):
    book = fp['book']
    lines = ['书名：%s' % (book.get('book') or ''),
             '判型（可能为空）：%s %s' % (book.get('原型') or '未定', book.get('原型名') or ''),
             '段数：%d，篇数：%d，对白率：%.1f%%，平均句长：%.1f 字'
             % (fp['stats']['段数'], fp['stats']['篇数'],
                fp['stats']['对白率'] * 100, fp['stats']['平均句长'])]
    if fp['outline']:
        names = [o.get('篇') or '' for o in fp['outline'][:20]]
        lines.append('篇名（前 20）：' + '；'.join(names))
    lines.append('')
    lines.append('抽样段落：')
    for r in fp['picks']:
        lines.append('【段 %s】%s' % (r.get('id'), (r.get('文本') or '')[:600]))
    lines.append('')
    lines.append('类别与定义：')
    for name, desc in COLUMNS:
        lines.append('- %s：%s' % (name, desc))
    lines.append('')
    lines.append('输出 JSON，形如：')
    lines.append('{"定义": {"适用": true, "置信": 0.8, "理由": "前段有「所谓…是指…」", "证据段": "%s"}, ...}'
                 % (fp['picks'][0].get('id') if fp['picks'] else ''))
    lines.append('每个类别都要出现；不确定就把「适用」写 false。')
    return '\n'.join(lines)


def parse_json(text):
    t = text.strip()
    t = re.sub(r'^```(?:json)?|```$', '', t, flags=re.M).strip()
    i, j = t.find('{'), t.rfind('}')
    if i < 0 or j <= i:
        raise ValueError('没有 JSON')
    return json.loads(t[i:j + 1])


def program_columns(code, fp):
    """自证列不交给模型：形态即结论，程序直接判。"""
    txt = '\n'.join((r.get('文本') or '') for r in fp['rows'])
    out = {}
    quotes = len(re.findall(r'《[^》]{2,20}》', txt))
    out['引书'] = {'适用': quotes >= 5, '置信': 1.0,
                   '理由': '正文出现《书名》%d 处' % quotes, '来源': '程序'}
    out['篇目'] = {'适用': len(fp['outline']) >= 5, '置信': 1.0,
                   '理由': '切出 %d 篇' % len(fp['outline']), '来源': '程序'}
    if (fp['book'].get('原型') or '') == 'P11':
        out['物种条目'] = {'适用': True, '置信': 1.0,
                           '理由': '判型为 P11 图鉴型', '来源': '程序'}
    return out


def judge(code, save=True):
    fp = fingerprint(code)
    prompt = build_prompt(fp)
    res = llm.chat([{'role': 'system', 'content': SYS},
                    {'role': 'user', 'content': prompt}],
                   max_tokens=2400, temperature=0, thinking=False, json_mode=True)
    data = parse_json(res['text'])
    clean = {}
    for name, _ in COLUMNS:
        v = data.get(name)
        if not isinstance(v, dict):
            continue
        clean[name] = {
            '适用': bool(v.get('适用')),
            '置信': float(v.get('置信') or 0),
            '理由': str(v.get('理由') or '')[:120],
            '证据段': str(v.get('证据段') or ''),
            '来源': '模型',
        }
    # 自证列以程序为准，覆盖模型判断
    for name, v in program_columns(code, fp).items():
        v['证据段'] = ''
        clean[name] = v
    if save:
        path = os.path.join(OUT, code, 'judge.json')
        with io.open(path, 'w', encoding='utf-8') as fpo:
            json.dump({'code': code, 'model': res['model'], 'prompt': PROMPT_VERSION,
                       'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'usage': res['usage'],
                       'columns': clean}, fpo, ensure_ascii=False, indent=1)
    return clean, res['usage']


if __name__ == '__main__':
    codes = sys.argv[1:] or ['B56', 'B58', 'B59', 'B60']
    for c in codes:
        cols, usage = judge(c)
        on = [k for k, v in cols.items() if v['适用']]
        print('%s 适用 %d/%d：%s' % (c, len(on), len(COLUMNS), '、'.join(on) or '（全不适用）'))
        for k, v in cols.items():
            if v['适用'] and v.get('来源') == '程序':
                print('    [程序] %s：%s' % (k, v['理由']))
        print('   tokens: prompt %s / completion %s' % (usage.get('prompt_tokens'), usage.get('completion_tokens')))

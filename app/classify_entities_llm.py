#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实体分类第二层：规则高置信直接留，模糊的交给模型看上下文。

- 规则层：行政区词典、机构/地标/奖项/事件/朝代等明确词形；
- 模型层：只处理规则拿不准的名字，带上下文，一次 40 个；
- 结果写 out/<code>/entity_types.json；单本人工覆盖仍以 entity_review.json 为准。
- 不写全局词典，不按书名写死名字。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app')
ENGINE = os.path.join(ROOT, 'platform', 'engine')
sys.path.insert(0, APP)
sys.path.insert(0, ENGINE)

import store          # noqa: E402
import llm            # noqa: E402
import entity_classify as EC  # noqa: E402

KEEP = {
    '行政区词典', '行政区词典补后缀', '机构后缀', '地标后缀', '自然地理后缀',
    '奖项后缀', '事件后缀', '朝代词表', '化石/古人类后缀', '食品', '学校简称',
    '机构科室', '分类阶元（动植物上下文）', '城市补表', '地理词典',
}

SYS = ('你是图书实体分类器。只根据名称和上下文，从固定类别中选一个；'
       '拿不准选 other，不要硬分。只输出 JSON。')

CATS = """country 国家（中国、美国）
province 省份（江苏、河北）
region 区域/大区（东北地区、华东）
city 城市（上海、南京）
district 区县（青浦县、杨浦区、安亭镇）
landmark 道路/地标（巨鹿路、文化广场、虹桥机场、宾馆、车站）
nature 自然地理（崇明岛、东海、华山）
fossil 化石/古人类（北京猿人）
org 机构（政府机关、法院、检察院、公司、工厂、学校、医院、出版社）
object 器物（车、船、工具、食品、公章、衣服）
animal 动物
plant 植物
taxon 科属（毛茛科、卷柏属）
alias 别名（原文明确写的别名/俗名）
person 人物（真实人物、角色）
concept 概念/术语（主义、理论、制度、观念、格局）
award 奖项（诺贝尔奖）
event 事件（战争、运动、事件、工程）
dynasty 朝代（唐、宋、五代）
family 家族（贾家）
other 拿不准"""

EXAMPLES = """示例：
- 上海市人民检察分院 → org（检察院机关）
- 徐家汇 → landmark（上海地名/商圈）
- 衡山（上下文“衡山饭店”）→ landmark
- 衡山（上下文“衡山山脉”）→ nature
- 江村 → district（村）
- 五代 → dynasty
- 黄门（上下文“黄门侍郎”）→ org
- 天国（上下文“上帝/灵魂”）→ concept
"""


def prompt(book, batch):
    lines = []
    for x in batch:
        lines.append('%s\t%s' % (x['name'], x['ctx'][:120].replace('\n', ' ')))
    return ('书名：%s\n\n类别：\n%s\n\n%s\n'
            '为下面每个候选判定一个类别。名称必须逐字照抄。\n'
            '严格输出 JSON：{"items":[{"name":"...","cat":"...","confidence":0.0,"reason":"..."}]}\n\n'
            '候选（名称\\t上下文）：\n%s' % (book, CATS, EXAMPLES, '\n'.join(lines)))


def parse(text):
    t = (text or '').strip()
    t = t.replace('```json', '').replace('```', '').strip()
    i, j = t.find('{'), t.rfind('}')
    if i >= 0 and j > i:
        t = t[i:j + 1]
    return json.loads(t)


def run(code, batch_size=40, force=False):
    rec = store.get_record(code) or {}
    book = rec.get('book') or code
    rows = store.read_jsonl(os.path.join(store.E.OUT, code, 'entities.jsonl'))
    segs = store._seg_texts(code)
    by_name = {}
    for r in rows:
        n = r.get('name')
        if not n:
            continue
        ctx = segs.get(r.get('seg') or '') or ''
        by_name.setdefault(n, ctx)
    types = {}
    todo = []
    for n, ctx in by_name.items():
        cat, conf, why = EC.classify(n, ctx)
        if (not force) and conf >= 0.9 and why in KEEP:
            types[n] = {'cat': cat, 'confidence': conf, 'reason': why, 'source': 'rule'}
        else:
            todo.append({'name': n, 'ctx': ctx})
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        try:
            r = llm.chat([{'role': 'system', 'content': SYS},
                          {'role': 'user', 'content': prompt(book, batch)}],
                         max_tokens=5000, temperature=0, json_mode=True)
            data = parse(r.get('text'))
        except Exception as e:
            print('  %s 批次失败：%s' % (code, e))
            continue
        names = {x['name'] for x in batch}
        for x in data.get('items') or []:
            n = (x.get('name') or '').strip()
            cat = (x.get('cat') or 'other').strip()
            if n not in names or cat not in EC.CATS + ('other',):
                continue
            types[n] = {'cat': cat, 'confidence': float(x.get('confidence') or 0.7),
                        'reason': (x.get('reason') or '模型分类')[:80], 'source': 'llm'}
        print('  %s %d/%d' % (code, min(i + batch_size, len(todo)), len(todo)))
    path = os.path.join(store.E.OUT, code, 'entity_types.json')
    tmp = path + '.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(types, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print('%s %s：规则 %d，模型 %d，共 %d' % (
        code, book[:20], sum(1 for v in types.values() if v['source'] == 'rule'),
        sum(1 for v in types.values() if v['source'] == 'llm'), len(types)))


if __name__ == '__main__':
    if not llm.ready():
        print('模型未配置')
        sys.exit(1)
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    force = '--force' in sys.argv
    for code in args or [b['code'] for b in store.library_rows()]:
        try:
            run(code, force=force)
        except Exception as e:
            print('%s 失败：%s' % (code, e))

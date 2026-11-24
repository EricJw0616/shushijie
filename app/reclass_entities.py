#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把所有书里“未分类专名”批量重洗一遍：人物 / 概念术语 / 实体类 / 丢弃。

只写人工审核覆盖表（entity_review.json），不改 entities.jsonl，可回退。
拿不准的保留 other，不硬分。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app')
ENGINE = os.path.join(ROOT, 'platform', 'engine')
sys.path.insert(0, APP)
sys.path.insert(0, ENGINE)

import store  # noqa: E402
import llm    # noqa: E402

CATS = {'person', 'concept', 'country', 'province', 'region', 'city', 'district', 'landmark', 'nature', 'fossil',
        'org', 'object', 'animal', 'plant', 'taxon', 'alias', 'award', 'event', 'dynasty', 'family'}
ALLOWED = CATS | {'drop', 'other'}

SYS = ('你是出版社的数据标注员。只根据给出的书名、候选名和上下文判断它属于哪一类；'
       '拿不准就选 other，不要硬分。只输出 JSON。')


def prompt(code, book, items):
    lines = []
    for x in items:
        lines.append('%s\t%d\t%s' % (x['name'], x.get('count') or 0, (x.get('snippet') or '')[:80]))
    return (
        '书名：%s\n\n下面是这本书里系统认不出类别的专名候选（名称\\t出现次数\\t上下文）：\n%s\n\n'
        '请为每个候选选一个类别：\n'
        '- person 人物（孔子、严复、费孝通、亚当·斯密）\n'
        '- concept 概念/术语（差序格局、西洋、儒家、浮士德式、礼俗社会）\n'
        '- country 国家（中国、美国、日本）\n'
        '- province 省份（江苏、河北、新疆）\n'
        '- region 区域/大区（东北地区、西北地区、华北）\n'
        '- city 城市（上海、南京、苏州）\n'
        '- district 区县（青浦县、杨浦区、安亭镇）\n'
        '- landmark 道路/地标（巨鹿路、文化广场、虹桥机场）\n'
        '- nature 自然地理（崇明岛、东海、华山）\n'
        '- fossil 化石/古人类（北京猿人、中国猿人）\n'
        '- org 机构（燕京大学、清华大学、出版社）\n'
        '- object 器物（工具、器物、作品名）\n'
        '- animal 动物 / plant 植物 / taxon 科属（动植物名、科属名）\n'
        '- alias 别名（原文明确标注的别名/俗名）\n'
        '- award 奖项（诺贝尔奖、国家最高科学技术奖等）\n'
        '- event 事件（文化大革命、李闻事件、田纳西工程等）\n'
        '- dynasty 朝代（秦汉、唐宋等）\n'
        '- family 家族（贾家等）\n'
        '- drop 无价值：残片、普通词、标点数字、重复、明显不是专名\n'
        '- other 拿不准，保留人工\n'
        '判断原则：指人的选 person；指学派/理论/制度/观念/术语的选 concept；'
        '“西洋/西方”在讨论文化模式时选 concept，指具体国家时选 place；'
        '“浮士德式的/阿波罗式的”这种带“的”的残片选 drop。\n'
        '严格输出 JSON：{"items":[{"name":"逐字照抄候选名","cat":"person|concept|country|province|city|district|landmark|nature|org|object|animal|plant|taxon|alias|award|event|dynasty|family|drop|other","reason":"一句话"}]}\n'
        '\n候选：\n' % (book, '\n'.join(lines))
    )


def parse(text):
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    i, j = t.find('{'), t.rfind('}')
    if i >= 0 and j > i:
        t = t[i:j + 1]
    return json.loads(t)


def run(code, book, dry=False):
    d = store.review_pending(code, limit=500)
    items = d.get('items') or []
    if not items:
        print('%s %s：没有待分类' % (code, book))
        return
    r = llm.chat([{'role': 'system', 'content': SYS},
                  {'role': 'user', 'content': prompt(code, book, items)}],
                 max_tokens=7000, temperature=0, json_mode=True)
    data = parse(r.get('text'))
    names = {x['name'] for x in items}
    counts = {}
    applied = 0
    for x in data.get('items') or []:
        name = (x.get('name') or '').strip()
        cat = (x.get('cat') or 'other').strip()
        if name not in names or cat not in ALLOWED:
            continue
        counts[cat] = counts.get(cat, 0) + 1
        if dry or cat == 'other':
            continue
        if cat == 'drop':
            store.set_entity_review(code, name, drop=True)
        else:
            store.set_entity_review(code, name, cat=cat)
        applied += 1
    after = store.review_pending(code, limit=1).get('count')
    print('%s %-24s 待分类 %3d → %3d｜%s' % (
        code, book[:22], len(items), after,
        '、'.join('%s=%d' % (k, v) for k, v in sorted(counts.items()))))


def main():
    codes = sys.argv[1:]
    if not codes or codes == ['--all']:
        codes = [b['code'] for b in store.library_rows()]
    if not llm.ready():
        print('模型未配置')
        return 1
    for code in codes:
        rec = store.get_record(code) or {}
        try:
            run(code, rec.get('book') or code)
        except Exception as e:
            print('%s 失败：%s' % (code, e))
    return 0


if __name__ == '__main__':
    sys.exit(main())

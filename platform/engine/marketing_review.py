# -*- coding: utf-8 -*-
"""营销草稿质检：第二遍模型审查 + 确定性过滤。

营销 7 项不是生成完就交付，必须再过一遍：
  - 关键词去掉书名、作者名、泛词、广告词、过长短语、过细无关词；
  - 简介检查 150–300 字、客观、覆盖全书（只报问题，不擅自重写）；
  - 五类检查 3–6 条，去掉空泛、无依据、重复的。

输出写回 marketing.json：过滤后的 value + review 记录；状态仍是 needs_review。
"""
import io
import json
import os
import re
import sys

import llm
import marketing as MK
import paths as P


def _load(code):
    p = os.path.join(P.OUT, code, 'marketing.json')
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None


def _save(code, rec):
    p = os.path.join(P.OUT, code, 'marketing.json')
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _call(prompt):
    r = llm.chat([
        {'role': 'system', 'content': '你是出版社营销总监，负责审稿。只依据给出的书稿片段和草稿判断，'
                                      '不引入书外知识。只输出 JSON。'},
        {'role': 'user', 'content': prompt}],
        max_tokens=2500, temperature=0, json_mode=True)
    t = (r.get('text') or '').strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    i, j = t.find('{'), t.rfind('}')
    return json.loads(t[i:j + 1])


def _rewrite_summary(code, rec):
    text, _ = MK.build_input(code, 10000)
    prompt = (
        '下面是一本书的原文片段和一段过长的内容简介。请把简介改写成 180–260 字的客观概述：'
        '保留书名、作者、核心内容与结构；不要罗列全部篇目；不要广告化；不加入原文没有的事实。'
        '只输出 JSON：{"summary":"..."}\n\n'
        '书名：%s\n\n原文片段：\n%s\n\n原简介：\n%s'
        % (rec.get('book') or '', text, rec['items']['summary']['value']['text'])
    )
    r = _call(prompt)
    return (r.get('summary') or '').strip()


def review(code, max_chars=8000):
    rec = _load(code)
    if not rec:
        raise SystemExit('没有 marketing.json：%s' % code)
    text, _ = MK.build_input(code, max_chars)
    draft = {k: v.get('value') for k, v in rec['items'].items()}
    prompt = (
        '书名：%s\n作者/出版信息见下。\n\n下面是这本书的原文片段：\n%s\n\n'
        '下面是已经生成的营销 7 项草稿（JSON）：\n%s\n\n'
        '请审查并输出 JSON：\n'
        '1) keywords_keep：保留的关键词（逐字照抄）；keywords_drop：去掉的，给 keyword+reason。\n'
        '   去掉：书名、作者名、泛词（人生/世界/生活/故事/思想/文化/回忆录/文集/作品）、'
        '广告词（重磅/必读/爆款）、过长短语（超过 12 字）、过细且与营销无关的词。\n'
        '2) summary_issue：简介的问题（字数不在 150–300、像目录堆砌、广告化、超出原文等）；'
        '没问题填空字符串。不要重写。\n'
        '3) drop：五类里要去掉的条目，{"audience":[{"text":"逐字照抄","reason":""}],...}；'
        '没有问题就给空数组。去掉空泛、无依据、重复、与书无关的。\n'
        '4) comment：一句总评。\n'
        '只输出：{"keywords_keep":[],"keywords_drop":[],"summary_issue":"",'
        '"drop":{"audience":[],"scenarios":[],"gains":[],"emotions":[],"leads":[]},'
        '"comment":""}'
        % (rec.get('book') or '', text, json.dumps(draft, ensure_ascii=False)[:12000])
    )
    r = _call(prompt)
    orig = {k: list(v.get('value') or []) for k, v in rec['items'].items()
            if k in ('keywords', 'audience', 'scenarios', 'gains', 'emotions', 'leads')}

    # 关键词过滤
    keep = [str(x).strip() for x in (r.get('keywords_keep') or []) if str(x).strip()]
    old = rec['items']['keywords']['value']
    by_kw = {x['keyword']: x for x in old}
    kept = [by_kw[k] for k in keep if k in by_kw]
    if len(kept) < 5:
        for x in old:
            if x not in kept:
                kept.append(x)
            if len(kept) >= 5:
                break
    dropped = [x for x in old if x['keyword'] not in {y['keyword'] for y in kept}]
    rec['items']['keywords']['value'] = kept
    rec['items']['keywords']['evidence'] = [e for x in kept for e in x['evidence']]
    rec['items']['keywords']['note'] = 'AI 草稿 + 第二遍审查；保留 %d 个' % len(kept)

    # 五类过滤
    drop_map = r.get('drop') or {}
    for key in ('audience', 'scenarios', 'gains', 'emotions', 'leads'):
        bad = {str(x.get('text') or '').strip() for x in (drop_map.get(key) or [])}
        it = rec['items'][key]
        vals = [x for x in it['value'] if str(x.get('text') or '').strip() not in bad]
        if len(vals) < 3:
            for x in orig.get(key) or []:
                if x not in vals:
                    vals.append(x)
                if len(vals) >= 3:
                    break
        it['value'] = vals
        it['evidence'] = [e for x in vals for e in x['evidence']]
        it['note'] = 'AI 草稿 + 第二遍审查；保留 %d 条' % len(vals)

    rec['review'] = {
        'model': llm.CFG.get('BOOKDISTILL_LLM_MODEL', ''),
        'comment': r.get('comment') or '',
        'summary_issue': r.get('summary_issue') or '',
        'keywords_dropped': [{'keyword': x['keyword'], 'reason': ''} for x in dropped],
        'items_dropped': {k: len(drop_map.get(k) or []) for k in drop_map},
    }
    if r.get('summary_issue'):
        issue = r['summary_issue']
        if ('超过' in issue or '300' in issue) and rec['items']['summary'].get('value'):
            try:
                new = _rewrite_summary(code, rec)
                if len(new) > 300:
                    cut = new[:300]
                    k = max(cut.rfind('。'), cut.rfind('；'), cut.rfind('！'))
                    if k >= 150:
                        new = cut[:k + 1]
                if 150 <= len(new) <= 300:
                    rec['items']['summary']['value'] = {'text': new}
                    rec['items']['summary']['note'] = 'AI 草稿；已按审查意见压缩到 %d 字' % len(new)
                    rec['review']['summary_rewritten'] = True
                else:
                    rec['items']['summary']['note'] = 'AI 草稿；审查问题：%s' % issue
            except Exception as e:
                rec['items']['summary']['note'] = 'AI 草稿；审查问题：%s（改写失败：%s）' % (issue, e)
        else:
            rec['items']['summary']['note'] = 'AI 草稿；审查问题：%s' % issue
    _save(code, rec)
    return rec


def main(argv):
    codes = argv[1:]
    if not codes:
        print(__doc__)
        return 2
    for c in codes:
        try:
            rec = review(c)
            print('%s %-24s 关键词 %d，读者 %d，场景 %d，收获 %d，情绪 %d，线索 %d'
                  % (c, rec['book'][:22],
                     len(rec['items']['keywords']['value']),
                     len(rec['items']['audience']['value']),
                     len(rec['items']['scenarios']['value']),
                     len(rec['items']['gains']['value']),
                     len(rec['items']['emotions']['value']),
                     len(rec['items']['leads']['value'])))
            if rec['review'].get('summary_issue'):
                print('   简介问题：%s' % rec['review']['summary_issue'])
        except Exception as e:
            print('%s 失败：%s' % (c, e))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

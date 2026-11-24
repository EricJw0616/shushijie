# -*- coding: utf-8 -*-
"""热点营销：六平台抓取 → 四维拆解 → 图书匹配。

逻辑对齐浙少中台 hotspot.py / match.py，简化为当前 JSON 数据：
- 抓取：newsnow 六平台，失败回退头条/百度/B站；
- 拆解：事情内核 / 情绪词 / 受众词 / 可关联关键词 / 风险；
- 匹配：关键词 45 + 情绪 20 + 受众 20 + 安全 15，无向量；
- 输出：命中理由、缺口、下一步，不藏分。
"""
import json
import os
import re
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import llm
from product_language import PRODUCT_LANGUAGE
import store

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
NEWSNOW = 'https://newsnow.busiyi.world/api/s?id=%s'
PLATFORMS = {'weibo': '微博热搜', 'zhihu': '知乎热榜', 'douyin': '抖音热点',
             'toutiao': '今日头条', 'baidu': '百度热搜', 'bilibili': 'B站热门'}

EMOTION_WORDS = (
    '焦虑 担忧 不安 恐惧 压力 疲惫 无力 委屈 愤怒 不满 抵触 反感 厌恶 失望 幻灭 无奈 '
    '被动 纠结 犹豫 困惑 孤独 内耗 自我怀疑 拖延 被误解 被忽视 不公平感 '
    '期待 好奇 兴奋 共鸣 感动 治愈 温暖 希望 释然 认可 赞赏 敬佩 自豪 安全感 渴望 向往 '
    '想改变 想突破 想被理解 想被看见 想省钱 想更好 不服 倔强 坚韧 '
    '理性 观望 怀疑 思辨 猎奇 调侃 讽刺 荒诞感 争议 分歧'
).split()
AUDIENCE_WORDS = (
    '大众 普通人 女性 男性 妈妈 爸爸 家长 学生 职场 工薪 年轻人 中年 中老年 读者 消费者 '
    '用户 粉丝 从业者 管理者 创业者 创作者 教师 公务员 自由职业 打工人 劳动者 '
    '家庭 婚恋 育儿 升学 求职 转型 低谷 独处 离乡 生病 照顾者 高压 迷茫 内卷 独居 新手 '
    '文学 历史 哲学 心理 社科 科技 艺术 传统文化 教育 财经 法律 健康 生活美学 旅行 美食'
).split()
RISK = {'无': 15, '低': 12, '中': 9, '高': 4}
MATCH_THRESHOLD = 85
# 图书营销文案里的说法 → 标准词表
SYN = {
    '孩子': '学生', '儿童': '学生', '青少年': '学生', '少年': '学生',
    '学校': '教师', '老师': '教师', '父母': '家长',
    '敬仰': '敬佩', '崇敬': '敬佩', '爱国': '自豪', '奋斗': '坚韧',
}


def _get(url, timeout=5):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode('utf-8', 'ignore')


def _newsnow(pid, limit):
    items = json.loads(_get(NEWSNOW % pid)).get('items', [])[:limit]
    out = []
    for i, it in enumerate(items, 1):
        extra = it.get('extra') or {}
        out.append({'rank': i, 'source': PLATFORMS.get(pid, pid),
                    'title': it.get('title', ''),
                    'heat': extra.get('info', '') if isinstance(extra, dict) else '',
                    'url': it.get('url', '')})
    return out


def _toutiao(limit):
    data = json.loads(_get('https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc')).get('data', [])
    return [{'rank': i, 'source': '今日头条', 'title': it.get('Title', ''),
             'heat': str(it.get('HotValue', '')), 'url': it.get('Url', '')}
            for i, it in enumerate(data[:limit], 1)]


def _baidu(limit):
    html = _get('https://top.baidu.com/board?tab=realtime')
    m = re.search(r'<!--s-data:(.*?)-->', html, re.S)
    if not m:
        return []
    cards = json.loads(m.group(1)).get('data', {}).get('cards', [])
    items = []
    for c in cards:
        items.extend(c.get('content', []))
    return [{'rank': i, 'source': '百度热搜', 'title': it.get('word', ''),
             'heat': str(it.get('hotScore', '')), 'url': it.get('rawUrl') or it.get('url', '')}
            for i, it in enumerate(items[:limit], 1)]


def _bilibili(limit):
    data = json.loads(_get('https://api.bilibili.com/x/web-interface/popular?ps=%d' % limit)).get('data', {}).get('list', [])
    return [{'rank': i, 'source': 'B站热门', 'title': it.get('title', ''),
             'heat': str(it.get('stat', {}).get('view', '')), 'url': it.get('url', '')}
            for i, it in enumerate(data[:limit], 1)]


def _get_json(url, ref=''):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': ref})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=6, context=ctx) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def _weibo(limit):
    d = _get_json('https://weibo.com/ajax/side/hotSearch', 'https://weibo.com/')
    rows = ((d.get('data') or {}).get('realtime') or [])[:limit]
    out = []
    for i, it in enumerate(rows, 1):
        out.append({'rank': it.get('realpos') or i, 'source': '微博热搜',
                    'title': it.get('word') or it.get('note') or '',
                    'heat': str(it.get('num') or ''), 'url': 'https://s.weibo.com/weibo?q=%23' + (it.get('word') or '') + '%23'})
    return out


def _douyin(limit):
    d = _get_json('https://www.douyin.com/aweme/v1/web/hot/search/list/', 'https://www.douyin.com/')
    data = d.get('data') or {}
    rows = (data.get('word_list') or data.get('trending_list') or [])[:limit]
    out = []
    for i, it in enumerate(rows, 1):
        out.append({'rank': i, 'source': '抖音热点',
                    'title': it.get('word') or '',
                    'heat': str(it.get('hot_value') or it.get('article_detail_count') or ''),
                    'url': 'https://www.douyin.com/hot'})
    return out


_FALLBACK = {'weibo': _weibo, 'douyin': _douyin, 'toutiao': _toutiao,
             'baidu': _baidu, 'bilibili': _bilibili}


def _one(pid, limit):
    try:
        return pid, _newsnow(pid, limit), None
    except Exception as e:
        if pid in _FALLBACK:
            try:
                return pid, _FALLBACK[pid](limit), None
            except Exception as e2:
                return pid, [], str(e2)[:120]
        return pid, [], str(e)[:120]


def fetch_all(limit=12):
    merged, errors = {}, {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        got = list(ex.map(lambda p: _one(p, limit), list(PLATFORMS)))
    for pid, items, err in got:
        if err:
            errors[PLATFORMS[pid]] = err
            continue
        for it in items:
            key = re.sub(r'[\s　，。！？、：:,.!?#【】\[\]()（）"\'“”‘’]+', '', it['title']).lower()
            if not key:
                continue
            if key not in merged:
                merged[key] = {'title': it['title'], 'sources': [], 'url': it.get('url', '')}
            merged[key]['sources'].append('%s#%d%s' % (
                it['source'], it['rank'], ('（%s）' % it['heat']) if it.get('heat') else ''))
    out = list(merged.values())
    out.sort(key=lambda x: len(x['sources']), reverse=True)
    return {'items': out[:60], 'errors': errors}


def _json(text):
    t = (text or '').strip().replace('```json', '').replace('```', '').strip()
    i, j = t.find('{'), t.rfind('}')
    if i >= 0 and j > i:
        t = t[i:j + 1]
    return json.loads(t)


def analyze(title, facts=''):
    title = (title or '').strip()
    if not title:
        raise ValueError('热点标题为空')
    if not llm.ready():
        return {'事情内核': title, '情绪内核词': [], '受众画像词': ['大众'],
                '可关联关键词': [x for x in re.split(r'[\s，。、：:；;！？!?]+', title) if x],
                '风险等级': '无', '风险说明': '模型未配置，基础版未评估风险',
                '借势建议': '配置模型后可获得四维拆解与借势建议', 'mode': 'basic'}
    system = ('你是出版行业营销分析师。为图书营销拆解社会热点，只输出一个 JSON。'
              '合同：{"事情内核":"一句话本质","情绪内核词":["..."],"受众画像词":["..."],'
              '"可关联关键词":["..."],"风险等级":"无|低|中|高","风险说明":"...","借势建议":"..."}')
    user = ('热点标题：%s\n已知事实：%s\n'
            '要求：\n1. 情绪词 3-6 个，只能从：%s 里挑；\n'
            '2. 受众词 3-6 个，只能从：%s 里挑；\n'
            '3. 可关联关键词 8-14 个，覆盖同义说法、人物、事件、概念；\n'
            '4. 风险：明星隐私/未判决案件/政治敏感→中或高；公共政策/民生→低或无；\n'
            '5. 借势建议说清适不适合图书借势、从什么角度切入。') % (
        title, facts or '（无补充，不要编造细节）', ' '.join(EMOTION_WORDS), ' '.join(AUDIENCE_WORDS))
    r = llm.chat([{'role': 'system', 'content': system + PRODUCT_LANGUAGE},
                  {'role': 'user', 'content': user}], max_tokens=1200, temperature=0, json_mode=True)
    d = _json(r.get('text'))
    emo = [w for w in (d.get('情绪内核词') or []) if w in EMOTION_WORDS][:6]
    aud = [w for w in (d.get('受众画像词') or []) if w in AUDIENCE_WORDS][:6] or ['大众']
    return {'事情内核': str(d.get('事情内核') or title)[:200],
            '情绪内核词': emo, '受众画像词': aud,
            '可关联关键词': [str(x)[:20] for x in (d.get('可关联关键词') or [])][:14] or [title],
            '风险等级': d.get('风险等级') if d.get('风险等级') in RISK else '无',
            '风险说明': str(d.get('风险说明') or '')[:200],
            '借势建议': str(d.get('借势建议') or '')[:300], 'mode': 'llm'}


def _terms(s):
    return [x.strip() for x in re.split(r'[,，、;；/\s]+', s or '') if x.strip()]


def _std_words(text, pool):
    out = set(w for w in pool if w in (text or ''))
    for k, v in SYN.items():
        if k in (text or '') and v in pool:
            out.add(v)
    return sorted(out)


def _overlap(hot, text):
    if not text:
        return []
    texts = [text] + _terms(text)
    out = []
    for h in hot:
        if any(h in t or (len(t) >= 2 and t in h) for t in texts if t):
            out.append(h)
    return out


def _book_meta(code):
    b = store.get_record(code) or {}
    import marketing_state
    materials = marketing_state.rows(code)
    def val(k):
        return ' '.join(r['text'] for r in materials if r['key'] == k)
    kw = val('keywords')
    intro = val('summary')
    cloud = val('gains') + ' ' + val('scenarios')
    quote = val('leads')
    aud = val('audience')
    emo = val('emotions')
    return {'code': code, 'title': b.get('book') or code,
            'author': b.get('author') or '', 'publisher': b.get('publisher') or '',
            'text': ' '.join([b.get('book') or '', kw, intro, cloud, quote, aud, emo]),
            'kw': kw, 'intro': intro, 'cloud': cloud, 'quote': quote,
            'aud': aud, 'emo': emo}


def preview(title, limit=2):
    """热点 → 图书的快速预览：只用标题关键词，不调模型。"""
    terms = [x for x in re.split(r'[\s，。、：:；;！？!?]+', title or '') if 2 <= len(x) <= 12]
    if not terms:
        return []
    books = [_book_meta(x['code']) for x in store.library_rows()]
    out = []
    for b in books:
        hits = _overlap(terms, b['text'])
        if not hits:
            continue
        score = round(45 * min(1, len(hits) / 4.0) + 15)
        out.append({'code': b['code'], 'title': b['title'], 'score': score,
                    'hits': hits[:4], 'reason': '命中：' + '、'.join(hits[:4])})
    out.sort(key=lambda x: -x['score'])
    return out[:limit]


def preview_many(titles, limit=2):
    return {t: preview(t, limit) for t in (titles or [])}


def match(analysis, limit=10):
    hk = list(analysis.get('可关联关键词') or [])
    he = list(analysis.get('情绪内核词') or [])
    ha = list(analysis.get('受众画像词') or [])
    risk = analysis.get('风险等级') or '无'
    if analysis.get('事情内核') and analysis['事情内核'] not in hk:
        hk = hk + [analysis['事情内核']]
    books = [_book_meta(x['code']) for x in store.library_rows()]
    results = []
    for b in books:
        hit_k = _overlap(hk, b['text'])
        # 图书情绪/受众：营销文案 + 同义词 → 标准词
        be = ' '.join(_std_words(b['text'], EMOTION_WORDS))
        ba = ' '.join(_std_words(b['text'], AUDIENCE_WORDS))
        hit_e = _overlap(he, be)
        hit_a = _overlap(ha, ba)
        s_k = 45 * min(1, len(hit_k) / 4.0)
        s_e = 20 * min(1, len(hit_e) / 3.0)
        s_a = 20 * min(1, len(hit_a) / 2.0)
        s_s = RISK.get(risk, 15)
        total = round(s_k + s_e + s_a + s_s)
        suitable = (total >= MATCH_THRESHOLD and s_s >= 5)
        level = 'ok' if suitable else ('mid' if total >= 70 else 'no')
        reasons = []
        if hit_k: reasons.append('关键词对得上：' + '、'.join(hit_k[:5]))
        if hit_e: reasons.append('情绪对得上：' + '、'.join(hit_e))
        if hit_a: reasons.append('读者对得上：' + '、'.join(hit_a))
        gaps = []
        if not hit_k: gaps.append('热点关键词没有直接命中书名/简介/卖点')
        if he and not hit_e: gaps.append('热点情绪与这本书的营销情绪没重合')
        if ha and not hit_a: gaps.append('热点受众与这本书的读者画像没重合')
        if not reasons: reasons.append('没有明显重合，不建议硬蹭')
        nxt = ('建议借势：点“看营销素材”，挑卖点/金句继续' if level == 'ok'
               else ('有条件：补更具体的热点事实再判' if level == 'mid'
                     else '暂不建议，换更贴近的书或角度'))
        results.append({'code': b['code'], 'title': b['title'], 'author': b['author'],
                        'publisher': b['publisher'], 'score': total, 'level': level,
                        'suitable': suitable,
                        'keyword': round(s_k, 1), 'emotion': round(s_e, 1),
                        'audience': round(s_a, 1), 'safety': s_s,
                        'hit_keywords': hit_k, 'hit_emotions': hit_e,
                        'hit_audience': hit_a, 'reasons': reasons, 'gaps': gaps,
                        'next': nxt})
    results.sort(key=lambda x: -x['score'])
    return results[:limit]

# -*- coding: utf-8 -*-
"""生成「图书标签数据库」页面。

2026-10-31 改版：由「一页到底、标签当入口」改为「书架 → 书详情」两级结构。

改版原因（用户反馈）：
  旧版首屏是标签 chip + 书列表，用户看不懂「这跟浙少那个中台有什么区别」。
  根本问题不在视觉，在入口逻辑：旧版先给标签、后给书，等于让人从词典进入一本书；
  真实使用是「我要看这本书」，进去之后再关心它被打了什么标签。
  中台的做法（先选书、进详情、所有能力围绕这本书展开）才是编辑的手感。

新版结构：
  书架视图   → 22 本书的卡片，每张写明原型/体量/标签数/有没有卡片
  书详情视图 → 八层标签逐层展开、每个标签可点开原文证据、三类卡片全文、该书缺口
  标签词典   → 全库视角，哪些标签真有区分度（辅助功能，不是主入口）
  局限说明   → 这批标签拿不到什么

设计约束（沿用旧版，未放宽）：
  1. 每个标签带「来源」与「验证」，三类来源定义写在页面上。
  2. 抽不出来的子类如实写「未抽出：人物」，不填占位。
  3. 数字全部实测填充，不 hardcode。
  4. 单文件、零外部依赖、双击可开，hash 路由支持前进后退。
"""
import json, io, os, html
import paths as P

BASE = P.PLATFORM
LIB = f'{BASE}/library'


def jf(p, d=None):
    if not os.path.exists(p):
        return d
    return json.load(io.open(p, encoding='utf-8'))


def jl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]


def esc(s):
    return html.escape(str(s), quote=False)


LAYER_META = [
    ('L5', '能力', '这本书能拿出什么产物'),
    ('L6', '概念', '书里哪一段在讲道理 — 论断段定位器，不是主题词表'),
    ('L7', '议题', '这本书能对上哪些现代议题 — 今用判断，非作者分类'),
    ('L4', '内容', '书里写了什么 — 必须读正文才拿得到'),
    ('L3', '类型', '属于哪一类书'),
    ('L2', '语体', '用什么语言写的'),
    ('L1', '结构', '怎么编的'),
    ('L0', '原文', '有多少字、可不可检索'),
]

SRC_STYLE = {
    '实测': ('#eef3e8', '#4a6b34', '程序从正文数出来的，可复算'),
    '抽取': ('#fdf1e0', '#8a5a1f', '正则从正文抽出来的，可回查锚点'),
    '判断': ('#f2ecf7', '#5a4070', '需要人定性的，标「待确认」'),
}

# L4 内容层的四个可指认实体类，按此顺序分组显示
L4_ORDER = ['人物', '引用书目', '篇名', '曲牌']
L4_HINT = {
    '人物': '书里被点名、且带称谓后缀的人。不带后缀的不算 —— 姓「关」「应」「于」「从」的都可能是常用词。',
    '引用书目': '书里提到别的书名。能看出这本书在跟谁对话，但古典书引得多、现代小说引得少，横向比书会错判。',
    '篇名': '作者自己起的小标题。是这本书的骨架，不是外部给的分类。',
    '曲牌': '只在戏曲型出现。非戏曲书里出现的【】是举例词的，不算本书曲牌。',
}


def link_cards(books, rules, topics, mirrors):
    """把三类卡片挂到书上。

    卡片表的书名各有写法（「闲情偶寄」vs 标签表的「2018版闲情偶寄」），
    因此优先用码匹配，码缺失时（mirrors 无码）退回书名字串包含匹配。
    匹配不上就如实不挂，不猜。
    """
    by_code = {b['码']: b for b in books}
    idx = {b['码']: {'rules': [], 'topics': [], 'mirrors': []} for b in books}

    def resolve(row):
        code = row.get('码')
        if code and code in idx:
            return code
        name = str(row.get('书', ''))
        for b in books:
            if name and (name in b['书'] or b['书'] in name):
                return b['码']
        return None

    for kind, rows in (('rules', rules), ('topics', topics), ('mirrors', mirrors)):
        for r in rows:
            c = resolve(r)
            if c:
                idx[c][kind].append(r)
    return idx, by_code


def main():
    T = jf(f'{LIB}/tags.json')
    TD = jf(f'{LIB}/tag_dict.json', [])
    MAN = jf(f'{LIB}/manifest.json', {})
    CAT = jf(f'{LIB}/catalog.json', [])
    rules = jl(f'{LIB}/rules.jsonl')
    topics = jl(f'{LIB}/topics.jsonl')
    mirrors = jl(f'{LIB}/mirrors.jsonl')

    books = T['书']
    card_idx, _ = link_cards(books, rules, topics, mirrors)

    # tags.json 不带判型置信与依据（那两项在 catalog.json），按码合并进来。
    # 不合并就会在页面上凭空写一个「置信」，那是编数据。
    cat_by = {c['码']: c for c in CAT}
    for b in books:
        c = cat_by.get(b['码'], {})
        b['置信'] = c.get('置信', '未评')
        b['依据'] = c.get('依据', [])
        b['图谱判定'] = c.get('图谱判定', '')
        # 人物抽取的能力边界也要合并：页面要靠它区分
        # 「书里没有人物关系」与「我们抽不出」，漏合并就退化成一句「不出图谱」。
        b['人物抽取边界'] = c.get('人物抽取边界') or {}
        b['强证据人物数'] = c.get('强证据人物数', 0)
        b['结构模式'] = c.get('结构模式', '')
        # 吻合度与合集构成也必须从 catalog 合并，否则页面上取不到，
        # 就会出现「整本判 P6」而不提「只有 40% 的块支持」的情况。
        b['吻合'] = c.get('吻合')
        b['合集'] = c.get('合集') or []

    n_book = len(books)
    n_tag = sum(len(b[k]) for b in books for k, _, _ in LAYER_META)
    n_uniq = len({t['标签'] for b in books for k, _, _ in LAYER_META for t in b[k]})
    n_strong = len([t for t in TD if t['区分度'] == '强'])
    n_card = len(rules) + len(topics) + len(mirrors)
    n_book_card = len([1 for b in books if any(card_idx[b['码']].values())])
    n_ev = sum(1 for b in books for k, _, _ in LAYER_META for t in b[k] if t.get('原文'))

    # 每本书的前置摘要，书架卡片用
    shelf = []
    for b in books:
        ci = card_idx[b['码']]
        l4 = b['L4']
        cnt4 = {}
        for t in l4:
            cnt4[t.get('类', '其他')] = cnt4.get(t.get('类', '其他'), 0) + 1
        shelf.append({
            '书': b['书'], '码': b['码'],
            '原型': b['原型'], '原型名': b['原型名'],
            '汉字': b['汉字'], '篇数': b['篇数'], '段数': b['段数'],
            '单位': b.get('代码单位') or '篇',
            '保留率': b.get('保留率'),
            '标签数': sum(len(b[k]) for k, _, _ in LAYER_META),
            '有内容': len(l4),
            '内容分项': cnt4,
            '规则卡': len(ci['rules']),
            '主题卡': len(ci['topics']),
            '易错卡': len(ci['mirrors']),
            '强证据人物数': b.get('强证据人物数', 0),
            '可出图谱': bool(b.get('可出关系图谱')),
            # 人物抽取的能力边界：开关状态 + 状语形态占比 + 判定语。
            # 页面要能说清「抽不出」与「书里没有」的区别，这一条是唯一的依据。
            '人物抽取边界': b.get('人物抽取边界') or {},
            '缺口': b.get('L4缺口') or '',
            # L7 议题名必须进书架：应用层「热点 → 找书」就靠这一个字段。
            # 只给数量没用，得让人一眼看出这本书能对上哪些议题。
            '议题': [t['标签'] for t in (b.get('L7') or [])],
            '议题数': len(b.get('L7') or []),
        })

    payload = {
        'books': books, 'shelf': shelf, 'layers': LAYER_META, 'src': SRC_STYLE,
        'cards': card_idx, 'dict': TD, 'l4order': L4_ORDER, 'l4hint': L4_HINT,
        'lim': {
            'rules': len(rules), 'topics': len(topics), 'mirrors': len(mirrors),
            'hans': MAN.get('汉字总数', 0), 'frag': MAN.get('片段总数', 0),
            'by_p': MAN.get('按原型', {}), 'cap': MAN.get('能力分层的书数', {}),
        },
    }
    pj = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')

    tpl = r'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>图书标签数据库 · 果麦</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f6f2e9;color:#2b2118;
 font-family:"Songti SC","SimSun",Georgia,serif;font-size:15px;line-height:1.7}
.wrap{max-width:1180px;margin:0 auto;padding:26px 24px 70px}
a{color:#8a4b2a;cursor:pointer;text-decoration:none}
a:hover{text-decoration:underline}

/* ---------- 顶栏 ---------- */
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
 border-bottom:2px solid #8a4b2a;padding-bottom:10px;margin-bottom:8px}
h1{font-size:24px;margin:0;letter-spacing:.03em}
.crumb{font-size:13px;color:#8b7b68}
.crumb b{color:#4a3d2e;font-weight:600}
.sub{color:#7a6a58;font-size:13px;margin:6px 0 18px}
.sub b{color:#8a4b2a;font-weight:600}

.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin:0 0 20px}
.stat{background:#fffdf8;border:1px solid #e4dbcb;border-radius:6px;padding:10px 12px}
.stat .n{font-size:21px;color:#8a4b2a;font-weight:600;line-height:1.2}
.stat .l{font-size:11px;color:#8b7b68;margin-top:2px;line-height:1.4}

/* ---------- 视图切换 ---------- */
nav{display:flex;gap:7px;margin-bottom:16px;flex-wrap:wrap}
nav button{padding:6px 14px;border:1px solid #d9cfbe;background:#fffdf8;border-radius:99px;
 cursor:pointer;font-family:inherit;font-size:13px;color:#4a3d2e}
nav button.on{background:#8a4b2a;color:#fffdf8;border-color:#8a4b2a}
nav button:hover{border-color:#8a4b2a}

/* ---------- 工具条 ---------- */
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.bar input{flex:1;min-width:190px;padding:8px 12px;border:1px solid #d9cfbe;border-radius:5px;
 font-family:inherit;font-size:13.5px;background:#fffdf8;outline:none}
.bar input:focus{border-color:#8a4b2a}
.bar select{padding:8px 10px;border:1px solid #d9cfbe;border-radius:5px;font-family:inherit;
 font-size:13px;background:#fffdf8;color:#4a3d2e;outline:none}

/* ---------- 书架 ---------- */
.shelf{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.shelf{grid-template-columns:repeat(2,1fr)}}
@media(max-width:620px){.shelf{grid-template-columns:1fr}}
.card{background:#fffdf8;border:1px solid #e4dbcb;border-radius:7px;padding:13px 15px 12px;
 cursor:pointer;transition:border-color .12s,background .12s;position:relative}
.card:hover{border-color:#8a4b2a;background:#fdf8ee}
.card .ttl{font-size:16px;font-weight:600;color:#3a2c1e;line-height:1.45;margin-bottom:3px}
.card .meta{font-size:11.5px;color:#8b7b68;margin-bottom:9px}
.pill{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;
 background:#f0e8d9;color:#6b5a46;margin-right:5px}
.pill.p{background:#efe3d0;color:#8a4b2a}
.card .line{font-size:12px;color:#6b5a46;border-top:1px solid #f0e8d9;padding-top:8px;
 display:flex;justify-content:space-between;gap:8px}
.card .cnt{color:#8a4b2a;font-weight:600}
.card .noc{color:#a89a86}
.badge{position:absolute;top:11px;right:13px;font-size:10.5px;padding:1px 6px;
 border-radius:3px;background:#eef3e8;color:#4a6b34}
.badge.none{background:#f2efe8;color:#a89a86}

/* ---------- 书详情 ---------- */
.head{background:#fffdf8;border:1px solid #e4dbcb;border-radius:7px;padding:16px 18px;margin-bottom:18px}
.head h2{margin:0 0 4px;font-size:21px;font-weight:600;border:none;padding:0}
.head .hm{font-size:12.5px;color:#8b7b68}
.head .hm b{color:#4a3d2e;font-weight:600}
.kv{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.kv span{font-size:11.5px;background:#f5efe3;color:#6b5a46;padding:2px 8px;border-radius:3px}

h3{font-size:15px;margin:24px 0 9px;padding-left:9px;border-left:3px solid #8a4b2a;
 display:flex;align-items:baseline;gap:8px}
h3 small{font-size:11.5px;color:#8b7b68;font-weight:400}
.note{font-size:12.5px;color:#8b7b68;margin:-3px 0 11px;line-height:1.75}

.lay{background:#fffdf8;border:1px solid #e4dbcb;border-radius:6px;padding:12px 14px 13px;margin-bottom:11px}
.layh{font-size:12px;color:#8b7b68;margin-bottom:7px;letter-spacing:.04em}
.layh b{color:#8a4b2a;font-weight:600;font-size:13px;margin-right:6px}

.chip{display:inline-block;padding:2px 8px;border-radius:3px;font-size:12px;
 margin:2px 4px 2px 0;white-space:nowrap;border:1px solid transparent;line-height:1.7}
.chip.ck{cursor:pointer;border-bottom:1px dotted currentColor}
.chip.ck:hover{filter:brightness(.96)}
.chip .v{opacity:.75;font-size:11px;margin-left:3px}
.evbox{display:none;margin:7px 0 9px;width:100%}
/* L7 议题卡：与 L4 的 chip 不同，议题需要「命中段数 + 原文 + 情绪/受众词」三行并排，
   否则读者看不出这个议题标签凭什么成立。 */
.tcard{border:1px solid #e5dccb;background:#fffdf8;border-radius:5px;
  padding:9px 11px;margin:0 0 8px;cursor:pointer;transition:border-color .15s}
.tcard:hover{border-color:#c9b89a}
.tc-h{display:flex;align-items:center;gap:8px;font-size:13px;color:#4a3a28}
.tc-h b{font-size:13.5px}
.tc-n{color:#8a7a66;font-size:11.5px}
.badge.jin{background:#f2ecf7;color:#5a4070;font-size:10.5px;
  padding:1px 5px;border-radius:3px;letter-spacing:.5px;
  /* .badge 的基础样式是给书架卡用的绝对定位，这里必须收回文档流，
     否则它按「最近的定位祖先」飞到页面右上角，卡片上根本看不到。 */
  position:static;top:auto;right:auto}
.tc-q{margin:5px 0 6px;font-size:12.5px;color:#6b5c4a;line-height:1.65;
  font-family:'Songti SC','SimSun',serif;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tc-k{display:flex;flex-wrap:wrap;gap:4px}
.kw{background:#eef3e8;color:#4a6b34;font-size:10.5px;padding:1px 6px;border-radius:3px}
.kw.aud{background:#fdf1e0;color:#8a5a1f}
.evbox.on{display:block}
.evh{font-size:11.5px;color:#8a5a1f;margin-bottom:4px}
.evh b{color:#4a3d2e}
.evt{background:#fbf6ec;border-left:2px solid #b89b76;padding:8px 11px;
 font-size:12.5px;color:#4a3d2e;line-height:1.85;white-space:pre-wrap}
.evt.none{color:#a89a86;font-style:normal}

.grp{margin-bottom:9px}
.grpt{font-size:11.5px;color:#8b7b68;margin-bottom:3px}
.grpt b{color:#4a3d2e;font-weight:600}
.grpt em{font-style:normal;color:#a89a86;font-size:11px;margin-left:6px}

/* 词典的层筛选条 */
.dbar{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin:2px 0 11px}
.dchip{font-size:11.5px;color:#6b5a46;background:#fffdf8;border:1px solid #e5dccb;
  border-radius:3px;padding:2px 9px;cursor:pointer;line-height:1.7}
.dchip:hover{border-color:#c9b89a}
.dchip.on{background:#8a4b2a;border-color:#8a4b2a;color:#fffdf8}
.dcount{margin-left:6px;font-size:11px;color:#a89a86}

/* 书架：卡片上的议题 chip 与顶部议题筛选条 */
.tchip{font-size:11px;color:#5a4070;background:#f2ecf7;border:1px solid #e6dcee;
  border-radius:3px;padding:1px 7px;cursor:default;line-height:1.6;white-space:nowrap}
.tchip.more{color:#8b7b68;background:#f7f3ea;border-color:#e5dccb}
.tchips{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:8px;min-height:0}
.topicbar{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-bottom:12px;
  background:#fffdf8;border:1px solid #e5dccb;border-radius:5px;padding:8px 11px}
.tbl{font-size:11.5px;color:#8b7b68;margin-right:4px}
.topicbar .tchip{cursor:pointer}
.topicbar .tchip:hover{border-color:#c9b89a}
.topicbar .tchip.on{background:#8a4b2a;border-color:#8a4b2a;color:#fffdf8}
.topicbar .tchip i{font-style:normal;opacity:.72;font-size:10px;margin-left:2px}
.topicbar .tchip.clear{background:transparent;border-style:dashed;color:#8b7b68}

/* ---------- 卡片 ---------- */
.rc,.tc,.mc{background:#fffdf8;border:1px solid #e4dbcb;border-left:3px solid #8a4b2a;
 border-radius:6px;padding:13px 16px;margin-bottom:11px}
.tc{border-left-color:#5f6b4a}
.mc{border-left-color:#a05c2c}
.rct{font-size:12px;color:#8b7b68;margin-bottom:7px;display:flex;gap:10px;flex-wrap:wrap}
.rct b{color:#8a4b2a;font-weight:600}
.rct .id{font-family:ui-monospace,monospace;color:#a89a86;font-size:11px}
.q{background:#fbf6ec;border-left:2px solid #b89b76;padding:8px 11px;margin:8px 0;
 font-size:13px;color:#4a3d2e;line-height:1.9}
.q::before{content:"原文｜";color:#a89a86;font-size:11px;margin-right:4px}
.row2{display:grid;grid-template-columns:52px 1fr;gap:6px 10px;font-size:12.5px;margin:6px 0}
.row2 dt{color:#8b7b68;font-size:11.5px}
.row2 dd{margin:0;color:#3a2c1e}
.bd{background:#fdf3e7;border:1px solid #e8d3b6;border-radius:4px;padding:8px 11px;
 font-size:12px;color:#8a6a3a;margin-top:8px;line-height:1.75}
.bd::before{content:"边界｜";font-weight:600}

.tsec{margin:9px 0;padding-left:0}
.tsec .th{font-size:12.5px;font-weight:600;color:#4a3d2e;margin-bottom:2px}
.tsec .tb{font-size:12.5px;color:#4a3d2e;line-height:1.85}
.tsec .tq{font-size:12px;color:#6b5a46;background:#fbf6ec;border-left:2px solid #cdd6c0;
 padding:6px 10px;margin-top:5px;line-height:1.8;white-space:pre-wrap}

.mrow{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:9px 0}
@media(max-width:760px){.mrow{grid-template-columns:1fr}}
.mbox{background:#fbf6ec;border-radius:4px;padding:8px 11px;font-size:12px;line-height:1.8}
.mbox .lbl{font-size:11px;color:#8b7b68;display:block;margin-bottom:2px}

.gap{background:#fdf3e7;border:1px solid #e8d3b6;border-radius:5px;padding:10px 13px;
 font-size:12.5px;color:#8a6a3a;margin:12px 0}
.warn{background:#fbeee8;border:1px solid #e8c4b4;border-radius:5px;padding:10px 13px;
 font-size:12.5px;color:#8a4a2a;margin:11px 0;line-height:1.8}
.ok{background:#eef3e8;border:1px solid #cdd6c0;border-radius:5px;padding:10px 13px;
 font-size:12.5px;color:#4a6b34;margin:11px 0;line-height:1.8}

table{width:100%;border-collapse:collapse;background:#fffdf8;font-size:12.5px}
th,td{border-bottom:1px solid #eee5d6;padding:7px 9px;text-align:left;vertical-align:top}
th{background:#efe8da;font-weight:600;font-size:12px;white-space:nowrap}
tr:hover td{background:#fbf6ec}
td a{color:#8a4b2a}

.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#7a6a58;margin-bottom:12px}
.pager{display:flex;justify-content:space-between;gap:10px;margin-top:26px;
 padding-top:14px;border-top:1px solid #e0d6c5;font-size:13px}
.pager .dis{color:#c0b3a0;cursor:default;text-decoration:none}
.foot{margin-top:36px;padding-top:15px;border-top:1px solid #e0d6c5;
 font-size:12px;color:#8b7b68;line-height:1.95}
.empty{padding:40px;text-align:center;color:#a89a86;font-size:13px}
</style></head><body><div class="wrap">

<header>
  <h1>图书标签数据库</h1>
  <div class="crumb" id="crumb"></div>
</header>
<div class="sub" id="sub"></div>

<div class="stats" id="stats"></div>
<nav id="nav">
  <button data-v="shelf" class="on">书架</button>
  <button data-v="dict">标签词典</button>
  <button data-v="limits">这批标签的边界</button>
</nav>

<div id="app"></div>

<div class="foot" id="foot"></div>
</div>

<script>
const D = __DATA__;
const LAYERS = D.layers, SRC = D.src;
const BOOKS = D.books, SHELF = D.shelf;
const BYSHELF = {}; SHELF.forEach(s=>BYSHELF[s['码']] = s);

function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

/* ================= 路由 ================= */
function route(){
  const h = location.hash.replace(/^#\/?/, '');
  if(!h) return {v:'shelf'};
  const i = h.indexOf('/');
  if(i<0) return {v:h};
  return {v:h.slice(0,i), arg:decodeURIComponent(h.slice(i+1))};
}
function go(p){ location.hash = '#/' + p; }
window.addEventListener('hashchange', render);

/* ================= 顶部 ================= */
const NET = D.lim;
function drawHead(cur){
  const crumb = document.getElementById('crumb');
  if(cur.v==='book'){
    const s = BYSHELF[cur.arg];
    crumb.innerHTML = `<a onclick="go('shelf')">书架</a> › <b>${esc(s?s['书']:cur.arg)}</b>`;
  }else if(cur.v==='dict'){
    crumb.innerHTML = `<a onclick="go('shelf')">书架</a> › <b>标签词典</b>`;
  }else if(cur.v==='limits'){
    crumb.innerHTML = `<a onclick="go('shelf')">书架</a> › <b>这批标签的边界</b>`;
  }else{
    crumb.innerHTML = '先选一本书，再看它的标签';
  }
  document.getElementById('sub').innerHTML =
    `<b>${BOOKS.length}</b> 本书 · <b>${NET.hans.toLocaleString()}</b> 汉字 · ` +
    `<b>${D.dict.length}</b> 个去重标签 · 全部从正文提取，不采外部书目库`;

  const n_uniq = D.dict.length;
  const n_tag = BOOKS.reduce((s,b)=>s+LAYERS.reduce((x,l)=>x+b[l[0]].length,0),0);
  const n_strong = D.dict.filter(t=>t['区分度']==='强').length;
  const n_card = NET.rules + NET.topics + NET.mirrors;
  const n_bc = SHELF.filter(s=>s['规则卡']+s['主题卡']+s['易错卡']>0).length;
  document.getElementById('stats').innerHTML = [
    [BOOKS.length,'入库图书'],[NET.hans.toLocaleString(),'汉字总量'],
    [n_tag,'标签条目'],[n_uniq,'去重标签'],[n_strong,'强区分标签'],
    [`${n_card} / ${n_bc} 本`,'卡片 / 有卡的书'],
  ].map(([n,l])=>`<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');

  [...document.querySelectorAll('#nav button')].forEach(b=>{
    b.classList.toggle('on', b.dataset.v===(cur.v==='book'?'shelf':cur.v));
  });
}

document.getElementById('foot').innerHTML = `
<b>三类来源的含义</b>（每个标签右上角标着）：
<span style="background:#eef3e8;color:#4a6b34;padding:1px 6px;border-radius:3px">实测</span>
＝ 程序从正文数出来的，可以拿原文自己复算一遍；
<span style="background:#fdf1e0;color:#8a5a1f;padding:1px 6px;border-radius:3px">抽取</span>
＝ 正则从正文抽出来的，每条带锚点，能翻到原文那一处；
<span style="background:#f2ecf7;color:#5a4070;padding:1px 6px;border-radius:3px">判断</span>
＝ 需要人定性的结论，标「待确认」，不当事实用。<br>
<b>不采外部数据</b>：这里没有一个标签来自豆瓣、开卷或出版社 ERP，全部由 ${NET.hans.toLocaleString()} 字正文提取而来。
好处是可回查、可复现；代价是不含 ISBN、定价、印数、销量这类书目字段 —— 那些字段正文里没有，需要另外接数据源。<br>
<b>生成方式</b>：<code>python engine/tagboard.py</code>，数据源为 <code>library/tags.json</code> 与三类卡片表，重跑数字自动更新。`;

/* ================= 书架 ================= */
let SF = {q:'', sort:'code', topic:''};
// 议题筛选项从书架数据现算，不写死 —— 写死就会和 L7 层不同步。
const TOPICS = (()=>{
  const m = {};
  SHELF.forEach(s=>(s['议题']||[]).forEach(t=>{ m[t]=(m[t]||0)+1; }));
  return Object.entries(m).sort((a,b)=>b[1]-a[1]);
})();
function shelfCards(){
  const q = SF.q.trim();
  let rows = SHELF.filter(s=>{
    if(SF.topic && (s['议题']||[]).indexOf(SF.topic)<0) return false;
    if(!q) return true;
    // 议题名也要能被搜到：应用层的人是从热点词开始找书，不是从书名开始。
    return (s['书']+' '+s['码']+' '+s['原型']+' '+s['原型名']+' '+(s['议题']||[]).join(' ')).indexOf(q)>=0;
  });
  if(SF.sort==='h') rows.sort((a,b)=>b['汉字']-a['汉字']);
  else if(SF.sort==='t') rows.sort((a,b)=>b['标签数']-a['标签数']);
  else if(SF.sort==='c') rows.sort((a,b)=>(b['规则卡']+b['主题卡']+b['易错卡'])-(a['规则卡']+a['主题卡']+a['易错卡']) || b['汉字']-a['汉字']);
  else rows.sort((a,b)=>a['码'].localeCompare(b['码']));

  const items = rows.map(s=>{
    const nc = s['规则卡']+s['主题卡']+s['易错卡'];
    const kinds = s['内容分项'];
    const kt = D.l4order.filter(k=>kinds[k]).map(k=>`${k} ${kinds[k]}`).join(' · ');
    const badge = nc ? `<span class="badge">有卡片</span>`
                     : `<span class="badge none">仅检索层</span>`;
    return `<div class="card" onclick="go('book/${s['码']}')">
      ${badge}
      <div class="ttl">${esc(s['书'])}</div>
      <div class="meta">
        <span class="pill p">${esc(s['原型'])} ${esc(s['原型名'])}</span>
        ${(s['汉字']/10000).toFixed(1)} 万字 · ${s['篇数']} ${esc(s['单位'])}
      </div>
      <div style="font-size:12px;color:#6b5a46;margin-bottom:8px;min-height:20px">
        ${kt ? `<span style="color:#8b7b68">内容：</span>${esc(kt)}` : '<span class="noc">内容层未抽出实体</span>'}
      </div>
      <div class="tchips">${(s['议题']||[]).slice(0,4).map(t=>`<span class="tchip">${esc(t)}</span>`).join('')}${
        (s['议题']||[]).length>4?`<span class="tchip more">+${s['议题'].length-4}</span>`:''}</div>
      <div class="line">
        <span><span class="cnt">${s['标签数']}</span> 个标签</span>
        <span>${nc ? `<span style="color:#8a4b2a">${nc} 张卡片</span>` : '<span class="noc">暂无卡片</span>'}</span>
      </div>
    </div>`;
  }).join('');
  return items || '<div class="empty">没有匹配的书。换个关键词。</div>';
}
function shelfView(){
  const tchips = TOPICS.slice(0,12).map(([t,n])=>
    `<span class="tchip${SF.topic===t?' on':''}" data-topic="${esc(t)}">${esc(t)} <i>${n}</i></span>`).join('');
  return `
  <div class="bar">
    <input id="sq" placeholder="搜书名、编号、原型、议题…（如「四世同堂」「P5」「权力与秩序」）" value="${esc(SF.q)}">
    <select id="ssort">
      <option value="code">按编号</option>
      <option value="h">按字数</option>
      <option value="t">按标签数</option>
      <option value="c">按有无卡片</option>
    </select>
  </div>
  <div class="topicbar">
    <span class="tbl">按议题找书</span>
    ${tchips || '<span class="noc">暂无议题标签</span>'}
    ${SF.topic?`<span class="tchip clear" data-topic="">清除筛选</span>`:''}
  </div>
  <div class="note" style="margin-bottom:14px">
    点任意一本书进详情。卡片标「仅检索层」的书只切了段落、抽了标签，
    <b>还没有可交付的卡片</b> —— 这个区别如实标在卡上，不合并成一个数。<br>
    议题是<b>今用判断</b>（整理者把古籍的定型说法归到现代议题上），不是作者原分类；
    它是给应用层做「热点词 → 找书」用的入口，点进书写详情能看到每条的整句原文。
  </div>
  <div class="shelf" id="shelfbox">${shelfCards()}</div>`;
}

function bindShelf(){
  const q = document.getElementById('sq');
  if(q){
    q.oninput = e=>{
      SF.q = e.target.value;
      drawShelfCards();   /* 只重绘卡片网格，不动输入框，否则每敲一个字光标就跳 */
    };
  }
  const sd = document.getElementById('ssort');
  if(sd){ sd.value = SF.sort; sd.onchange = e=>{ SF.sort = e.target.value; drawShelfCards(); }; }
  document.querySelectorAll('.topicbar .tchip').forEach(c=>{
    c.onclick = ()=>{
      SF.topic = (c.dataset.topic || '');
      // 议题条自身要重绘（高亮状态变了），但输入框不能重绘，所以分开处理
      const bar = document.querySelector('.topicbar');
      if(bar){
        const tchips = TOPICS.slice(0,12).map(([t,n])=>
          `<span class="tchip${SF.topic===t?' on':''}" data-topic="${esc(t)}">${esc(t)} <i>${n}</i></span>`).join('');
        bar.innerHTML = `<span class="tbl">按议题找书</span>${tchips}${
          SF.topic?'<span class="tchip clear" data-topic="">清除筛选</span>':''}`;
        bindShelf();
      }
      drawShelfCards();
    };
  });
}
function drawShelfCards(){
  const box = document.getElementById('shelfbox');
  if(box) box.innerHTML = shelfCards();
}

/* ================= 书详情 ================= */
function chipHTML(t, key){
  const s = SRC[t['来源']] || ['#eee','#666',''];
  const has = !!t['原文'];
  const st = t['状态'] ? `<span class="v">${esc(t['状态'])}</span>` : '';
  const val = t['值'] ? `<span class="v">· ${esc(t['值'])}</span>` : '';
  const rid = 'ev_' + key;
  const click = has ? ` onclick="showEv('${rid}', ${JSON.stringify(t['标签']).replace(/"/g,'&quot;')})"` : '';
  return `<span class="chip${has?' ck':''}"${click}
    title="${esc(t['来源'])}：${esc(t['验证']||'')}${has?'（点开看原文）':''}"
    style="background:${s[0]};color:${s[1]}">${esc(t['标签'])}${val}${st}</span>${has?`<div class="evbox" id="${rid}"></div>`:''}`;
}

function showEv(rid, tag){
  const box = document.getElementById(rid);
  if(!box) return;
  const key = rid + '|' + tag;
  if(box.dataset.k === key && box.classList.contains('on')){ box.classList.remove('on'); return; }
  box.dataset.k = key;
  box.classList.add('on');
  const t = findTag(tag);
  if(!t){ box.innerHTML = ''; return; }
  box.innerHTML = `<div class="evh"><b>${esc(t['标签'])}</b> · ${esc(t['来源'])} · ${esc(t['验证']||'')}
      ${t['锚点']?`<span style="color:#a89a86">｜锚点 ${esc(t['锚点'])}</span>`:''}</div>
    <div class="evt${t['原文']?'':' none'}">${esc(t['原文'] || '（该标签无原文片段：属于统计结论，不是引文）')}</div>`;
}

let CURBOOK = null;
function findTag(tag){
  if(!CURBOOK) return null;
  for(const l of LAYERS){ for(const t of CURBOOK[l[0]]){ if(t['标签']===tag) return t; } }
  return null;
}

function layerBlock(l, keyBase, book){
  const arr = book[l[0]];
  if(!arr.length) return '';
  // L6 概念层：不逐条列「论断篇」。
  // 这一层的价值是「哪一段在讲道理」，列 448 个「论断篇：XX」对读者没有意义，
  // 真正要看的是论断段的**总段数**和**它是什么**（定位器，不是主题词）。
  // 所以这里只给一行说明 + 篇数分布，详细段落交给 argu 数据源。
  if(l[0]==='L6'){
    const nseg = arr.reduce((s,t)=>s+(parseInt(t['值'])||0),0);
    return `<div class="lay">
      <div class="layh"><b>${l[0]} ${esc(l[1])}</b>${esc(l[2])}</div>
      <div class="grp">
        <div class="grpt"><b>论断段定位器</b> ${arr.length} 篇 / ${nseg} 段
          <em>这一层只标「哪一段在讲道理」，不出主题词。实测定型句式抽出的概念名七成是跨句碎片，宁可不出。</em></div>
        ${arr.slice(0,24).map((t,i)=>chipHTML(t, keyBase+'_6_'+i)).join('')}
        ${arr.length>24?`<span class="more">…另有 ${arr.length-24} 篇，见 argu.jsonl</span>`:''}
      </div>
    </div>`;
  }
  // L7 议题层：与 L4 专名不同，这一层是「今用判断」，必须把性质写死在卡片上。
  // 每条议题带：命中段数 / 论断段数 / 情绪词 / 受众词 / 整句原文。
  // 情绪词与受众词用的是与营销侧同一套标准词（坚果云《热点抓取》那 126 个），
  // 目的是让「热点 → 书」两边能直接对词，不用再翻译一次。
  if(l[0]==='L7'){
    return `<div class="lay">
      <div class="layh"><b>${l[0]} ${esc(l[1])}</b>${esc(l[2])} · 共 ${arr.length} 个议题</div>
      <div class="grp">
        <div class="grpt"><b>议题标签</b>
          <em>性质是「今用」：议题归属是整理者的判断，不是作者原分类。古人没有「职场」「内耗」这些概念，说《论语》讲某个现代议题，是把它当作该议题的讨论素材，不是声称古人说过这句话。每条都可点开看整句原文。</em></div>
        ${arr.map((t,i)=>{
          const emo = (t['情绪词']||[]).map(x=>`<span class="kw">${esc(x)}</span>`).join('');
          const aud = (t['受众词']||[]).map(x=>`<span class="kw aud">${esc(x)}</span>`).join('');
          const rid = 'ev_' + keyBase + '_7_' + i;
          return `<div class="tcard" onclick="showEv('${rid}', ${JSON.stringify(t['标签']).replace(/"/g,'&quot;')})">
            <div class="evbox" id="${rid}"></div>
            <div class="tc-h"><b>${esc(t['标签'])}</b>
              <span class="tc-n">${esc(t['值'])}${t['论断段数']?`（其中 ${t['论断段数']} 段是论断段）`:''}</span>
              <span class="badge jin">今用</span></div>
            <div class="tc-q">${esc((t['原文']||'').slice(0,74))}</div>
            <div class="tc-k">${emo}${aud}</div>
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }
  if(l[0]==='L4'){
    const groups = {};
    arr.forEach(t=>{ const k = t['类'] || '其他'; (groups[k] = groups[k]||[]).push(t); });
    const order = D.l4order.filter(k=>groups[k]).concat(Object.keys(groups).filter(k=>D.l4order.indexOf(k)<0));
    return `<div class="lay">
      <div class="layh"><b>${l[0]} ${esc(l[1])}</b>${esc(l[2])} · 共 ${arr.length} 条</div>
      ${order.map((k,gi)=>{
        const rid = `${keyBase}_${gi}`;
        return `<div class="grp">
          <div class="grpt"><b>${esc(k)}</b> ${groups[k].length} 条<em>${esc(D.l4hint[k]||'')}</em></div>
          ${groups[k].map((t,ti)=>chipHTML(t, rid+'_'+ti)).join('')}
        </div>`;
      }).join('')}
    </div>`;
  }
  const rid = keyBase + '_0';
  return `<div class="lay">
    <div class="layh"><b>${l[0]} ${esc(l[1])}</b>${esc(l[2])} · ${arr.length} 条</div>
    ${arr.map((t,i)=>chipHTML(t, rid+'_'+i)).join('')}
  </div>`;
}

/* 三类卡片的渲染 */
function renderRules(list){
  if(!list.length) return '';
  return list.map(r=>`
    <div class="rc">
      <div class="rct">
        <b>${esc(r['领域']||'规则')}</b>
        <span>${esc(r['类型']||'')}</span>
        ${r['可照做']?'<span style="color:#4a6b34">可照做</span>':'<span style="color:#8a6a3a">条件性</span>'}
        <span class="id">${esc(r['id']||'')}</span>
        <span style="color:#a89a86">${esc(r['出处']||'')}</span>
      </div>
      <dl class="row2">
        <dt>条件</dt><dd>${esc(r['条件']||'')}</dd>
        <dt>动作</dt><dd>${esc(r['动作']||'')}</dd>
      </dl>
      <div class="q">${esc(r['原文']||'')}</div>
      ${r['边界']?`<div class="bd">${esc(r['边界'])}</div>`:'<div class="warn">此卡缺「边界」字段，用之前需人工确认前提。</div>'}
      ${r['校记']?`<div class="note" style="margin:8px 0 0">校记：${esc(r['校记'])}</div>`:''}
    </div>`).join('');
}

function renderTopics(list){
  if(!list.length) return '';
  return list.map(t=>`
    <div class="tc">
      <div class="rct"><b>${esc(t['类型']||'主题卡')}</b>
        <span class="id">${esc(t['id']||'')}</span>
        <span style="color:#a89a86">依据 ${t['依据段数']||0} 段 / 跨 ${t['跨度']||0} 段 / 覆盖 ${t['覆盖篇数']||0} 篇（全书 ${t['全书段数']||0} 段 ${t['全书篇数']||0} 篇）</span>
      </div>
      <div style="font-size:15px;font-weight:600;color:#3a2c1e;margin:2px 0 3px">${esc(t['主题']||'')}</div>
      <div style="font-size:12.5px;color:#6b5a46;line-height:1.8">${esc(t['副']||'')}</div>
      ${t['为什么难读']?`<div class="bd" style="background:#f5efe3;border-color:#e0d6c5;color:#6b5a46">为什么难读｜${esc(t['为什么难读'])}</div>`:''}
      ${(t['层']||[]).map(x=>`<div class="tsec">
        <div class="th">${esc(x['题']||'')}</div>
        <div class="tb">${esc(x['文']||'')}</div>
        ${x['引']?`<div class="tq">${esc(x['引'])}${x['锚点']?`　<span style="color:#a89a86;font-size:11px">［${esc(x['锚点'])}］</span>`:''}</div>`:''}
      </div>`).join('')}
      ${(t['对照']||[]).map(x=>`<div style="margin:11px 0;padding:9px 11px;background:#fbf6ec;border-radius:4px">
        <div style="font-size:11.5px;color:#8b7b68;margin-bottom:5px">对照｜${esc((x['题']||'').replace(/\n/g,' / '))}</div>
        <div class="mrow">
          <div class="mbox"><span class="lbl">甲 −</span>${esc(x['甲减']||'')}${x['甲锚']?`<div style="font-size:10.5px;color:#a89a86">［${esc(x['甲锚'])}］</div>`:''}</div>
          <div class="mbox"><span class="lbl">乙 ＋</span>${esc(x['乙加']||'')}${x['乙锚']?`<div style="font-size:10.5px;color:#a89a86">［${esc(x['乙锚'])}］</div>`:''}</div>
        </div>
        <div style="font-size:12px;color:#4a3d2e;line-height:1.8">辨｜${esc(x['辨']||'')}</div>
      </div>`).join('')}
      ${t['结论']?`<div class="ok" style="background:#f5efe3;border-color:#e0d6c5;color:#4a3d2e">结论｜${esc(t['结论'])}</div>`:''}
    </div>`).join('');
}

function renderMirrors(list){
  if(!list.length) return '';
  return list.map(m=>`
    <div class="mc">
      <div class="rct"><b>易错点</b><span class="id">${esc(m['id']||'')}</span>
        <span style="color:#8a4b2a">${esc(m['主题']||'')}</span></div>
      <div class="mrow">
        <div class="mbox" style="background:#fbeee8"><span class="lbl">你大概会读成</span>${esc(m['你大概会读成']||'')}</div>
        <div class="mbox" style="background:#eef3e8"><span class="lbl">原文另有一处相反说法</span>${esc(m['原文另有一处相反说法']||'')}</div>
      </div>
      <div style="font-size:12.5px;color:#3a2c1e;line-height:1.85;margin-top:6px">差别在哪｜${esc(m['差别在哪']||'')}</div>
      ${m['甲引']?`<div class="q" style="border-left-color:#d8b4a4">${esc(m['甲引'])}　<span style="color:#a89a86;font-size:11px">［${esc(m['甲锚']||'')}］</span></div>`:''}
      ${m['乙引']?`<div class="q" style="border-left-color:#b9c9a8">${esc(m['乙引'])}　<span style="color:#a89a86;font-size:11px">［${esc(m['乙锚']||'')}］</span></div>`:''}
    </div>`).join('');
}

function bookView(code){
  const book = BOOKS.find(b=>b['码']===code);
  if(!book) return `<div class="empty">找不到编号为 ${esc(code)} 的书。<a onclick="go('shelf')">回书架</a></div>`;
  CURBOOK = book;
  const s = BYSHELF[code] || {};
  const ci = D.cards[code] || {rules:[],topics:[],mirrors:[]};
  const nc = ci.rules.length + ci.topics.length + ci.mirrors.length;
  const idx = SHELF.findIndex(x=>x['码']===code);
  const prev = SHELF[idx-1], next = SHELF[idx+1];

  const layers = LAYERS.map((l,li)=>layerBlock(l, 'L'+li, book)).join('');

  const cardHTML = nc ? `
    <h3>这本书的卡片 <small>共 ${nc} 张 · 引文均已逐字回查通过</small></h3>
    ${ci.rules.length?`<div class="note" style="margin-bottom:8px">规则卡 ${ci.rules.length} 张 —— 可直接照着做，但必须连同「边界」一起读。</div>${renderRules(ci.rules)}`:''}
    ${ci.topics.length?`<div class="note" style="margin-bottom:8px">主题卡 ${ci.topics.length} 张 —— 把散在多篇里的同一层意思叠起来。</div>${renderTopics(ci.topics)}`:''}
    ${ci.mirrors.length?`<div class="note" style="margin-bottom:8px">易错对照 ${ci.mirrors.length} 张 —— 同一本书里两处说法方向相反，只读一处就会读反。</div>${renderMirrors(ci.mirrors)}`:''}
  ` : `<h3>这本书的卡片</h3>
    <div class="warn">
      <b>本书目前只有检索层，没有可交付的卡片。</b>
      已做的是：切段 ${book['段数']} 段、标八层标签 ${s['标签数']||0} 个、每条抽出的标签都能翻回原文。
      未做的是：知识卡、规则卡、主题卡、易错对照 —— 这些需要针对具体书做整理，机器按模板硬套会产出一堆看着对、实际不可用的卡。
      所以这里留空，不填占位卡片。
    </div>`;

  const gap = book.get ? '' : '';
  const gapHTML = s['缺口'] ? `<div class="gap">内容层缺口：${esc(s['缺口'])} —— 这一类实体在本书里没有可靠的抽取特征，如实留空，不拿别类顶替。</div>` : '';

  const ab = book['人物抽取边界'] || {};
  // 「这本书没有人物关系」与「我们的方法抽不出」必须分开显示。
  // 前者是关于书的结论，后者是我们的能力边界 —— 混成一句就是把缺陷冒充成结论。
  const ablHTML = ab['句首率门槛已启用']
    ? `<div class="gap">人物抽取边界：本书状语阻断句式占 ${(ab['状语形态占比']*100).toFixed(1)}%（全库文言/章回体普遍 &lt;5%），
       「瑞宣先笑了一下，而后声音很低的说」这类句式会让说话人位置切到状语上。
       本工具在这类现代白话文上抽不出可信人物表，<b>这不是「书里没有人物关系」，是方法边界</b>。
       需要人物图谱请人工给名单。</div>`
    : '';
  const peopleNote = (book['强证据人物数']||0) < 6
    ? `<div class="note">人物图谱：强证据人物 ${book['强证据人物数']||0} 人（出图需 ≥6 人），本书不出关系图谱。${esc(book['图谱判定']||'')}</div>`
    : `<div class="ok">人物图谱：强证据人物 ${book['强证据人物数']} 人，可出关系图谱（名单仍需人工确认）。</div>`;

  return `
  <div class="head">
    <h2>${esc(book['书'])}</h2>
    <div class="hm">编号 <b>${esc(book['码'])}</b> ·
      <span class="pill p">${esc(book['原型'])} ${esc(book['原型名'])}</span>
      判型置信 ${esc(book['置信']||'未评')}</div>
    ${(book['吻合']!=null && book['吻合']<100)?`<div class="warn" style="margin:9px 0 0">
      <b>「整本属于这一类」这句话，只在 ${book['吻合']}% 的分块上成立。</b>
      把全书切成 10 块分别判型，只有 ${book['吻合']}% 的块判成同一类。
      ${esc(book['原型'])} 只是占比最大的那一类，不代表全书内容都属于它。
    </div>`:''}
    ${(book['合集']||[]).length?`<div class="kv" style="margin:9px 0 0">
      <span><b>本书是多文体合集</b></span>
      ${book['合集'].map(function(p){return '<span>'+esc(p[0])+' '+p[1]+'%</span>'}).join('')}
    </div>`:''}
    <div class="kv">
      <span>${book['汉字'].toLocaleString()} 汉字</span>
      <span>${book['篇数']} ${esc(s['单位']||'篇')}</span>
      <span>${book['段数']} 段可检索</span>
      <span>清洗保留率 ${esc(book['保留率'])}%</span>
      <span>${s['标签数']||0} 个标签</span>
      <span>${nc} 张卡片</span>
    </div>
    ${(book['依据']||[]).length?`<div class="note" style="margin:9px 0 0">判型依据：${book['依据'].map(esc).join('；')}</div>`:''}
  </div>

  <h3>八层标签 <small>点带下划线的标签，就地展开它的原文证据</small></h3>
  <div class="legend">
    ${Object.entries(SRC).map(([k,v])=>`<span><b style="background:${v[0]};color:${v[1]};padding:1px 6px;border-radius:3px">${k}</b> ${esc(v[2])}</span>`).join('')}
  </div>
  ${layers}
  ${gapHTML}

  ${cardHTML}

  <h3>这本书的能力边界</h3>
  ${peopleNote}
  ${ablHTML}
  <div class="note">
    以上全部为候选结论：标签可由程序复算，卡片引文可逐字回查，但「这本书讲了什么」仍须人读。
    本页不做摘要、不写推荐语、不生成营销文案 —— 那些需要模型参与，参与后结论就不再可复算。
  </div>

  <div class="pager">
    ${prev?`<a onclick="go('book/${prev['码']}')">← ${esc(prev['书'])}</a>`:'<span class="dis">← 已是第一本</span>'}
    <a onclick="go('shelf')">回书架</a>
    ${next?`<a onclick="go('book/${next['码']}')">${esc(next['书'])} →</a>`:'<span class="dis">已是最后一本 →</span>'}
  </div>`;
}

/* ================= 标签词典 ================= */
// 词典要能按层看。L7 议题只有 15 个，且是「今用判断」，
// 混在 800 多个 L4 专名里根本找不到；而它恰恰是接热点匹配最需要被翻到的一层。
let DICT_LAY = '';
function dictView(){
  const all = D.dict;
  // L7 只有 15 个，不存在「区分不了书」的问题，一律全列；
  // 其余层只列出现 8 本以内的（出现更广的如「白话」区分不了书，留在书详情页）。
  let rows = all.filter(t=>t['层']==='L7' || t['书数']<=8);
  if(DICT_LAY) rows = rows.filter(t=>t['层']===DICT_LAY);
  rows = rows.slice().sort((a,b)=>a['书数']-b['书数']);
  const layBtn = [['','全部'],['L7','L7 议题'],['L6','L6 概念'],['L4','L4 内容'],
                  ['L3','L3 类型'],['L2','L2 语体'],['L1','L1 结构'],['L0','L0 原文'],
                  ['L5','L5 能力']]
    .map(([k,t])=>`<span class="dchip${DICT_LAY===k?' on':''}" data-lay="${k}">${t}</span>`).join('');
  const hint = DICT_LAY==='L7'
    ? '议题归属是整理者的「今用」判断，不是作者原分类。点书名进详情可看每条的整句原文与命中段数。'
    : '只列出现 8 本以内的标签。出现 9 本以上的（如「白话」「全文可检索」）留在这本书自己的详情页里，不上这张表 —— 它们区分不了书。点书名进详情。';
  return `
  <div class="note">${hint}</div>
  <div class="dbar">${layBtn}<span class="dcount">当前 ${rows.length} 个标签</span></div>
  <table><thead><tr>
    <th style="width:170px">标签</th><th style="width:52px">层</th>
    <th style="width:56px">书数</th><th style="width:62px">区分度</th><th>涉及的书</th>
  </tr></thead><tbody>
  ${rows.map(t=>`<tr>
    <td><b>${esc(t['标签'])}</b></td>
    <td>${esc(t['层'])}</td>
    <td>${t['书数']}</td>
    <td><span style="color:${t['区分度']==='强'?'#4a6b34':t['区分度']==='中'?'#8a5a1f':'#8b7b68'}">${esc(t['区分度'])}</span></td>
    <td style="color:#6b5a46">${t['书'].map(n=>{
      const c = (SHELF.find(s=>s['书']===n)||{})['码'];
      return c?`<a onclick="go('book/${c}')">${esc(n)}</a>`:esc(n);
    }).join('、')}</td>
  </tr>`).join('')}
  </tbody></table>`;
}

// 层筛选只重绘词典容器，不整页重绘（整页重绘会让滚动位置跳回顶部）。
function bindDict(){
  document.querySelectorAll('.dchip').forEach(c=>{
    c.onclick = ()=>{ DICT_LAY = c.dataset.lay; document.getElementById('app').innerHTML = dictView(); bindDict(); };
  });
}

/* ================= 边界 ================= */
function limitsView(){
  const bp = Object.entries(NET.by_p||{}).map(([k,v])=>`${esc(k)} ${v}`).join(' · ');
  const cap = Object.entries(NET.cap||{}).map(([k,v])=>`${esc(k)} ${v} 本`).join(' · ');
  return `
  <div class="warn">
    <b>训练集是空的。</b>${NET.rules} 张规则卡 + ${NET.topics} 张主题卡 + ${NET.mirrors} 张易错对照，共 ${NET.rules+NET.topics+NET.mirrors} 张，
    只是可以做训练集的<b>种子</b>，不是训练集本身。转成 SFT 或评测集还缺扩量、负样本、分布控制、train/dev/test 切分。
    为凑量去合成改写，会破坏「每句能翻回原文」这个唯一的立身之本。
  </div>
  <div class="warn">
    <b>人物只出带称谓后缀的。</b>实测把「关于」「应当」「后面」「从他」判成人物 ——
    姓氏法把关、应、于、从都当姓，这是中文人名与常用词同形的硬上限，纯统计分不开。
    现在只收「XX先生/太太/小姐/老爷」这类，数量少但都是真人物；要完整人物表，必须先人工给名单。
  </div>
  <div class="warn">
    <b>内容层不是「主题词表」，是「可指认的实体」。</b>
    四类只有篇名、引用书目、人物、曲牌。<b>没有一类是「这本书讲什么」的抽象主题</b>（如「启蒙」「权力」「科学精神」）——
    那需要人读完再归纳，机器硬抽会抽成虚词（试过：熵最高的全是「没有」「然而」「因为」）。
  </div>
  <div class="warn">
    <b>「引用书目」有已知偏斜：</b>古典书引经据典多，现代小说引用少。四世同堂三册只抽出 1–4 条，
    不是书里没内容，是它不点名引用 —— 拿这个数字横向比书会错判。
  </div>
  <div class="warn">
    <b>没有的字段：</b>ISBN、定价、印数、销量、读者对象年龄、中图分类分类。
    这些正文里不存在，必须另接数据源。本页面一律留空，不猜。
  </div>
  <h3>这批书的原型分布</h3>
  <div class="note">${bp}</div>
  <h3>能力分层</h3>
  <div class="note">${cap}</div>
  <div class="note">
    数字口径：${BOOKS.length} 本 / ${NET.hans.toLocaleString()} 汉字 / ${NET.frag.toLocaleString()} 个可检索片段。
    「段」是按古籍或现代章节切开的可检索单位，不是页面，也不是句子。
  </div>`;
}

/* ================= 渲染 ================= */
function render(){
  const cur = route();
  drawHead(cur);
  const app = document.getElementById('app');
  if(cur.v==='book'){ app.innerHTML = bookView(cur.arg); }
  else if(cur.v==='dict'){ app.innerHTML = dictView(); bindDict(); }
  else if(cur.v==='limits'){ app.innerHTML = limitsView(); }
  else { app.innerHTML = shelfView(); bindShelf(); }
  window.scrollTo(0,0);
}

document.querySelectorAll('#nav button').forEach(b=>{
  b.onclick = ()=> go(b.dataset.v);
});
render();
</script>
</body></html>'''

    doc = tpl.replace('__DATA__', pj)
    out = f'{BASE}/图书标签数据库.html'
    io.open(out, 'w', encoding='utf-8').write(doc)
    print(f'写出 {os.path.relpath(out, P.ROOT)}   {len(doc):,} 字符')
    print(f'  书 {n_book} / 标签 {n_tag} / 去重 {n_uniq} / 强区分 {n_strong}')
    print(f'  卡片 规则{nw(rules)} 主题{nw(topics)} 易错{nw(mirrors)} / 有卡的书 {n_book_card}')
    print(f'  带原文证据的标签 {n_ev}')


def nw(x):
    return len(x)


if __name__ == '__main__':
    main()

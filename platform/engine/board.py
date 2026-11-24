# -*- coding: utf-8 -*-
"""生成平台看板：书库 → 判型 → 产物 → 卡片 → 原文溯源。

设计要点（都是踩过坑之后定下的）：
  1. 数字全部由 catalog 实测填充，禁写死；页面出现的每个数都要能对上。
  2. 明确区分「已交付」与「按判型应有但尚未做」——不能把未做的显示成有。
  3. 卡片详情不设 max-height，原文依据必须直接可见。
  4. 高亮切片按句末标点 + 省略号，不按逗号（会切出短语导致无高亮）。
  5. 单文件、零外部依赖。
"""
import json, io, os, html, re
import paths as P

BASE = P.PLATFORM
LIB = f'{BASE}/library'
OUT = f'{BASE}/out'


def jl(p):
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]


def jf(p):
    return json.load(io.open(p, encoding='utf-8'))


def esc(s):
    return html.escape(str(s), quote=False)


def cut(s, n=120):
    s = s.strip()
    return s if len(s) <= n else s[:n] + '…'


def main():
    cat = jf(f'{LIB}/catalog.json')
    man = jf(f'{LIB}/manifest.json')
    rules = jl(f'{LIB}/rules.jsonl')
    topics = jl(f'{LIB}/topics.jsonl')
    mirrors = jl(f'{LIB}/mirrors.jsonl')
    cands = jl(f'{LIB}/cards_candidate.jsonl')

    # 只给需要的书装原文，控制体积
    need = {c['码'] for c in cat if c['已做卡片']}
    segs = {}
    for code in need:
        segs[code] = {s['id']: s for s in jl(f'{OUT}/{code}/segments.jsonl')}

    # 候选卡不进页面全量：2818 条精简后仍有 798 KB，整页会过重。
    # 页面只放「按书×类型」的数量表 + 每类 2 条样例（供判断抽取器准不准），
    # 全量清单在 library/cards_candidate.jsonl，页面写明路径。
    from collections import Counter, defaultdict
    cand_stat = defaultdict(Counter)      # 书 → 类型 → 数量
    sample = defaultdict(list)            # 类型 → 样例（最多 2 条）
    meta = {}                             # 类型 → (精度, 资产性质, 说明)
    for c in cands:
        cand_stat[c['书']][c['类型']] += 1
        if c['类型'] not in meta:
            meta[c['类型']] = (c.get('精度', '中'), c.get('资产性质', '需人筛'),
                              c.get('精度说明', ''))
        if len(sample[c['类型']]) < 2:
            sample[c['类型']].append({
                '书': c['书'], '锚点': c['锚点'],
                '原文': cut(c.get('原文', ''), 90),
                '待补': c.get('待补') or [],
            })
    cand_types = [k for k, _ in Counter(
        c['类型'] for c in cands).most_common()]
    # 按「精度」汇总：这是回答「每一类图书到底能给到什么结果」的硬数字。
    # 三类分开报，不许把「定位器」算进「可直接用」。
    grade = defaultdict(int)
    for c in cands:
        grade[c.get('资产性质', '需人筛')] += 1

    payload = {
        'catalog': cat,
        'manifest': man,
        'rules': rules,
        'topics': topics,
        'mirrors': mirrors,
        'segs': segs,
        'cand': {
            'total': len(cands),
            'types': cand_types,
            'bys': {b: dict(v) for b, v in cand_stat.items()},
            'sample': {k: v for k, v in sample.items()},
            'meta': meta,
            'grade': dict(grade),
        },
    }

    # 产物定义：名字 → 能力层
    PROD = [
        ('segments', '片段+锚点', 'L0 检索'),
        ('outline', '结构索引', 'L0 检索'),
        ('names', '专名表', 'L0 检索'),
        ('qupai', '曲牌索引', 'L0 检索'),
        ('kejie', '科介索引', 'L0 检索'),
        ('people', '人物候选', 'L1 需复核'),
        ('cards_candidate', '候选卡', 'L2a 待确认'),
        ('rules', '规则卡', 'L2b 已确认'),
        ('topics', '主题卡', 'L2b 已确认'),
    ]

    pj = json.dumps(payload, ensure_ascii=False)

    html_doc = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>出版内容平台 · 书库看板</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f6f2e9;color:#2b2118;
 font-family:"Songti SC","SimSun",Georgia,serif;font-size:15px;line-height:1.7}}
.wrap{{max-width:1180px;margin:0 auto;padding:32px 24px 80px}}
h1{{font-size:28px;margin:0 0 6px;letter-spacing:.04em}}
.sub{{color:#7a6a58;font-size:13.5px;margin-bottom:26px}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:28px}}
.stat{{background:#fffdf8;border:1px solid #e4dbcb;border-radius:6px;padding:12px 14px}}
.stat .n{{font-size:24px;color:#8a4b2a;font-weight:600;line-height:1.2}}
.stat .l{{font-size:11.5px;color:#8b7b68;margin-top:2px}}
h2{{font-size:18px;margin:34px 0 12px;padding-left:10px;border-left:3px solid #8a4b2a}}
.note{{font-size:12.5px;color:#8b7b68;margin:-6px 0 14px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}}
.tab{{padding:5px 13px;border:1px solid #d9cfbe;background:#fffdf8;border-radius:99px;
 cursor:pointer;font-size:13px;user-select:none}}
.tab.on{{background:#8a4b2a;color:#fffdf8;border-color:#8a4b2a}}
table{{width:100%;border-collapse:collapse;background:#fffdf8;font-size:13px}}
th,td{{border-bottom:1px solid #eee5d6;padding:8px 9px;text-align:left;vertical-align:top}}
th{{background:#efe8da;font-weight:600;font-size:12.5px;white-space:nowrap}}
tr:hover td{{background:#fbf6ec}}
.bk{{font-weight:600;cursor:pointer}}
.bk:hover{{color:#8a4b2a}}
.tag{{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11.5px;
 background:#eae2d2;color:#6b5a46;white-space:nowrap}}
.tag.p3{{background:#e6efe0;color:#41602f}}
.tag.p4{{background:#e5e9f2;color:#33456b}}
.tag.p6{{background:#f3e8e2;color:#7a4530}}
.tag.p7{{background:#f0e9f4;color:#5a3d68}}
.tag.p2{{background:#e4f0f0;color:#2c5a5a}}
.tag.p11{{background:#e8f0e4;color:#3d5c33}}
.tag.p12{{background:#f3efe2;color:#6b5a2e}}
.tag.p5,.tag.p8,.tag.p9,.tag.p1{{background:#efe6d8;color:#6b4f2a}}
.ok{{color:#3f6b33;font-weight:600}}
.no{{color:#b0a292}}
.card{{background:#fffdf8;border:1px solid #e4dbcb;border-left:3px solid #8a4b2a;
 border-radius:5px;padding:14px 16px;margin-bottom:12px}}
.card .t{{font-weight:600;font-size:15px;margin-bottom:4px}}
.card .q{{font-size:13px;color:#5f5140}}
.qz{{background:#f4eee0;border-left:2px solid #b89b76;padding:8px 11px;margin:7px 0;
 font-size:13px;color:#4a3d2e}}
.qz.hit{{background:#fdf0d5;border-left-color:#c07a2a}}
.lbl{{font-size:11.5px;color:#8b7b68;margin-right:5px}}
.bar{{display:inline-block;height:9px;background:#c9b79a;border-radius:2px;vertical-align:middle}}
.bar.hot{{background:#8a4b2a}}
.hid{{display:none}}
.foot{{margin-top:44px;padding-top:16px;border-top:1px solid #e0d6c5;
 font-size:12px;color:#8b7b68;line-height:1.9}}
.warn{{background:#fdf3e7;border:1px solid #e8d3b6;border-radius:5px;
 padding:11px 14px;font-size:12.5px;color:#7a5a33;margin:12px 0}}
code{{background:#efe8da;padding:1px 5px;border-radius:3px;font-size:12px}}
</style></head><body><div class="wrap">

<h1>出版内容平台 · 书库看板</h1>
<div class="sub">{man['书数']} 本实测 · 判型只作建议不硬拦截 · 每张卡的原文逐字可回查才出库</div>

<div class="stats">
  <div class="stat"><div class="n">{man['书数']}</div><div class="l">入库图书</div></div>
  <div class="stat"><div class="n">{man['汉字总数']:,}</div><div class="l">汉字总量</div></div>
  <div class="stat"><div class="n">{man['片段总数']:,}</div><div class="l">可检索片段</div></div>
  <div class="stat"><div class="n">{man.get('候选卡', 0):,}</div><div class="l">候选卡（待确认）</div></div>
  <div class="stat"><div class="n">{man['规则卡']+man['主题卡']+man['易错对照']}</div><div class="l">已确认卡片</div></div>
  <div class="stat"><div class="n">{len(man['按原型'])}</div><div class="l">产出原型</div></div>
</div>

<h2>一、书库总表：每本书能出什么</h2>
<div class="note">「产物」列只标已实际跑出来的；判型建议出但尚未做的，列在最后一列，不算交付。</div>
<div class="tabs" id="tabs"></div>
<table id="tb">
<thead><tr>
<th>书</th><th>原型</th><th>置信</th><th>篇/章</th><th>段</th><th>汉字</th>
<th>保留率</th><th>已交付产物</th><th>判型建议但未做</th>
</tr></thead><tbody id="tbody"></tbody></table>

<div class="warn">
<b>读这张表要注意三件事：</b><br>
① <b>保留率</b>＝清洗切段后保留的原文汉字比例，全部 ≥99.5%。低于 95% 视为切篇丢内容，不出库。<br>
② <b>已交付</b>不含「人物候选」以外的人工判断产物。人物表一律是<b>候选</b>，须确认后才能出关系图谱。<br>
③ <b>判型建议但未做</b>不是失败，是排期。平台按书排期，不按书承诺。
</div>

<h2>二、产物矩阵：原型 × 产物</h2>
<div class="note">一格一本书。同一原型的书能出的东西相同，但数量差很多——数量不写在这里，见下表。</div>
<div id="matrix"></div>

<h2>三、产物的数量实测</h2>
<div class="note">左边条形是本书该产物的数量，长度按全书最大值归一。空白＝该类书不出此产物。</div>
<div id="quant"></div>

<h2>四、候选卡层：机器铺的底稿</h2>
<div class="note">
候选卡＝按原型从原文抽出的结构化条目，机器已过一遍「原文必须逐字可回查」的校验。
<b>它们不是知识卡</b>：词条、名单、条目名是抽出来的，白话定义与边界还没人写。
本层的作用是把「人工从零开始翻书」变成「人工在候选里挑」。
全量清单：<code>platform/library/cards_candidate.jsonl</code>。
</div>

<div class="warn">
<b>为什么候选卡必须与已确认卡片分开放：</b>候选卡的字段是抽取器填的，不是人写的判断。
混在一起会让下游把机器推断当人工确认——这是本项目最不能犯的错。
所以：<b>已确认 {man['规则卡']+man['主题卡']+man['易错对照']} 条</b>（平台产线内、人工整理、过引文回查）
与<b>候选 {man.get('候选卡', 0):,} 条</b>（机器抽取、待确认）分开计数，不合并。<br>
另：《孙子兵法》另有 200 条人工卡在 <code>distill/</code>（早先独立流程，不在书库 56 本内），
若要并入本页需先做锚点对齐，暂不计入上方数字。
</div>

<div class="tabs" id="candtabs"></div>
<div id="gradebox" style="margin-bottom:14px"></div>
<div id="candbody"></div>

<h2>五、已确认的卡片</h2>
<div class="note">点卡片展开原文依据。每条引文都能在对应片段里逐字查到，查不到的不进这张表。</div>
<div class="tabs" id="ctabs"></div>
<div id="cards"></div>

<h2>六、原文溯源</h2>
<div class="note">选一本有卡片的书，看某段原文被哪些卡引用。这是双向溯源的另一半。</div>
<div id="trace"></div>

<div class="foot">
底本：果麦内文 PDF 抽取文本，仅作工序验证，不对外分发。<br>
数字口径：汉字＝CJK 基本区＋扩展 A＋兼容区＋扩展 B，不含拉丁字母与数字。<br>
平台只对已通过质检的卡片开放调用；候选与建议不作为交付物。
</div>
</div>

<script>
const D = {pj};
const PROD = {json.dumps(PROD, ensure_ascii=False)};
const ARCH_ORDER = ['P1','P2','P3','P4','P5','P6','P7','P8','P9','P10','P11','P12'];

function esc(s){{return String(s).replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}

/* ---------- 书库总表 ---------- */
let curArch = 'ALL';
function renderTabs(){{
  const box = document.getElementById('tabs');
  const arches = [...new Set(D.catalog.map(c=>c.原型))];
  const items = [['ALL','全部 '+D.catalog.length]]
    .concat(ARCH_ORDER.filter(a=>arches.includes(a))
      .map(a=>[a, a+' '+D.catalog.find(c=>c.原型===a).原型名+
        ' '+D.catalog.filter(c=>c.原型===a).length]));
  box.innerHTML = items.map(([k,label])=>
    `<div class="tab ${{k===curArch?'on':''}}" data-k="${{k}}">${{esc(label)}}</div>`).join('');
  box.querySelectorAll('.tab').forEach(el=>el.onclick=()=>{{
    curArch = el.dataset.k; renderTabs(); renderTable();
  }});
}}
function prodCell(p){{
  const got = PROD.filter(([k,n,lv])=>p[k]).map(([k,n])=>`<span class="tag">${{n}}</span>`);
  return got.length? got.join(' ') : '<span class="no">—</span>';
}}
function renderTable(){{
  const rows = D.catalog.filter(c=>curArch==='ALL'||c.原型===curArch);
  document.getElementById('tbody').innerHTML = rows.map(c=>{{
    const decl = c.原型==='P3'?['规则卡+边界','主题卡','镜像矛盾']
      :c.原型==='P2'?['概念卡','先修图谱','术语表','易错点']
      :c.原型==='P4'?['人物关系图谱','情节链','场所索引']
      :c.原型==='P5'?['人物关系图谱','出目情节链','曲牌科介索引']
      :c.原型==='P6'?['引书谱','意象谱','态度演变曲线']
      :c.原型==='P7'?['意象谱','名句索引','韵律统计']
      :c.原型==='P8'?['词条结构化','交叉引用','属性表']
      :c.原型==='P9'?['篇目索引','注疏分层','异文对照']
      :c.原型==='P10'?['条目索引','专名表','引书谱']
      :c.原型==='P11'?['物种条目卡','字段表','科名索引']
      :c.原型==='P12'?['人物条目','篇目索引','引书谱']
      :['规范型规则卡','条款索引','换版差异表'];
    const notdone = decl.filter(x=>!(
      (x.includes('规则')&&c.产物.rules)||
      (x.includes('主题')&&c.产物.topics)||
      (x.includes('人物')&&c.产物.people)));
    const r = c.特征;
    // 拒判书的 原型 是 null。旧代码直接 c.原型.toLowerCase() 会抛
    // TypeError，整张表渲染中断 —— 之前 tab 里没有 P1/P10，拒判书
    // 恰好被后置的 filter 挡住才没暴露。加空值兜底，不许再靠巧合。
    const pk = (c.原型 || 'P0').toLowerCase();
    const pn = c.原型 || 'P0';
    return `<tr>
      <td class="bk" data-code="${{c.码}}">${{esc(c.书)}}</td>
      <td><span class="tag ${{pk}}">${{pn}} ${{esc(c.原型名)}}</span></td>
      <td>${{esc(c.置信)}}</td>
      <td>${{c.篇数}}</td><td>${{c.段数}}</td><td>${{c.汉字.toLocaleString()}}</td>
      <td class="${{c.保留率>=95?'ok':'no'}}">${{c.保留率}}%</td>
      <td>${{prodCell(c.产物)}}</td>
      <td style="color:#a09080;font-size:12px">${{notdone.length?notdone.map(esc).join(' / '):'—'}}</td>
    </tr>`;
  }}).join('');
  document.querySelectorAll('.bk').forEach(el=>el.onclick=()=>{{
    const c = D.catalog.find(x=>x.码===el.dataset.code);
    alert(`${{c.书}}\\n\\n原型：${{c.原型}} ${{c.原型名}}（${{c.置信}}）\\n依据：${{c.依据.join('；')}}\\n\\n结构：${{c.结构模式}} / 按「${{c.结构单位}}」切，共 ${{c.篇数}} 个\\n`+
      `片段：${{c.段数}} 段，${{c.汉字.toLocaleString()}} 字，保留率 ${{c.保留率}}%\\n\\n`+
      `六轴：R规范${{c.特征.R}} D定义${{c.特征.D}} A议论${{c.特征.A}} `+
      `Q对白${{c.特征.Q}}% 文言${{c.特征.wen}} 第一人称${{c.特征.p1}}\\n`+
      `句均长${{c.特征.savg}} 句中位${{c.特征.smed}}\\n\\n`+
      `关系图谱：${{c.可出关系图谱?'可出':'不出'}}\\n${{c.图谱判定}}`);
  }});
}}

/* ---------- 产物矩阵 ---------- */
function renderMatrix(){{
  const arches = ARCH_ORDER.filter(a=>D.catalog.some(c=>c.原型===a));
  // 候选卡这一行显示「书数/总条数」，不只显示书数：
  // 只看「2/2 有候选」会以为 P1 和 P4 的产出量级相当，
  // 实际 P1 共 77 条、P4 共 1022 条，差 13 倍。数量必须一同给出。
  let h = '<table><thead><tr><th>产物</th><th>能力层</th>';
  arches.forEach(a=>h+=`<th>${{a}}</th>`);
  h += '</tr></thead><tbody>';
  PROD.forEach(([k,n,lv])=>{{
    h += `<tr><td>${{n}}</td><td><span class="tag">${{lv}}</span></td>`;
    arches.forEach(a=>{{
      const bs = D.catalog.filter(c=>c.原型===a);
      const hit = bs.filter(c=>c.产物[k]).length;
      if (k === 'cards_candidate' && hit) {{
        const tot = bs.reduce((s,c)=>s+(c.候选卡数||0),0);
        h += `<td><span class="ok">${{hit}}/${{bs.length}}</span>
          <div style="font-size:11px;color:#8b7b68">${{tot}} 条</div></td>`;
      }} else {{
        h += `<td>${{hit?`<span class="ok">${{hit}}/${{bs.length}}</span>`:'<span class="no">—</span>'}}</td>`;
      }}
    }});
    h += '</tr>';
  }});
  h += '</tbody></table>';
  document.getElementById('matrix').innerHTML = h;
}}

/* ---------- 数量实测条形 ---------- */
function renderQuant(){{
  const items = [
    ['片段 segments', c=>c.段数],
    ['结构 outline', c=>c.篇数],
    ['专名 names', c=>c.产物.names?1:0],
    ['人物候选 people', c=>c.强证据人物数],
  ];
  let h = '<table><thead><tr><th>书</th><th>片段</th><th>篇/章</th><th>人物候选(强证据)</th></tr></thead><tbody>';
  const maxSeg = Math.max(...D.catalog.map(c=>c.段数));
  const maxPpl = Math.max(1, ...D.catalog.map(c=>c.强证据人物数));
  D.catalog.forEach(c=>{{
    h += `<tr><td>${{esc(c.书)}}</td>
      <td><span class="bar" style="width:${{Math.round(c.段数/maxSeg*150)}}px"></span> ${{c.段数}}</td>
      <td><span class="bar" style="width:${{Math.round(c.篇数/Math.max(1,...D.catalog.map(x=>x.篇数))*110)}}px"></span> ${{c.篇数}}</td>
      <td>${{c.强证据人物数?`<span class="bar hot" style="width:${{Math.round(c.强证据人物数/maxPpl*110)}}px"></span> ${{c.强证据人物数}}`:'<span class="no">不出</span>'}}</td>
    </tr>`;
  }});
  h += '</tbody></table>';
  document.getElementById('quant').innerHTML = h;
}}

/* ---------- 卡片 ---------- */
let curCard = 'rules';
function renderCTabs(){{
  const items = [
    ['rules', `规则卡 ${{D.rules.length}}`],
    ['topics', `主题卡 ${{D.topics.length}}`],
    ['mirrors', `易错对照 ${{D.mirrors.length}}`],
  ];
  document.getElementById('ctabs').innerHTML = items.map(([k,l])=>
    `<div class="tab ${{k===curCard?'on':''}}" data-k="${{k}}">${{l}}</div>`).join('');
  document.querySelectorAll('#ctabs .tab').forEach(el=>el.onclick=()=>{{
    curCard = el.dataset.k; renderCTabs(); renderCards();
  }});
}}
function hl(text, quote){{
  /* 引文高亮：按句末标点+省略号切片，逐片包裹 */
  const parts = quote.split(/…+|\\.\\.\\./).map(s=>s.trim()).filter(Boolean);
  let out = esc(text);
  parts.forEach(p=>{{
    const q = esc(p);
    if (!out.includes(q)) return;
    out = out.replace(q, `<mark style="background:#fde3a7">${{q}}</mark>`);
  }});
  return out;
}}
function segOf(code, anchor){{
  const m = D.segs[code] || {{}};
  return m[anchor] || null;
}}
function renderCards(){{
  const box = document.getElementById('cards');
  if (curCard==='rules') {{
    box.innerHTML = D.rules.map(r=>{{
      const s = segOf(r.码, r.锚点);
      return `<div class="card">
        <div class="t">${{esc(r.主题||r.领域)}} <span class="tag">${{esc(r.id)}}</span></div>
        <div class="q"><span class="lbl">如果</span>${{esc(r.条件)}}</div>
        <div class="q"><span class="lbl">那就</span>${{esc(r.动作)}}</div>
        <div class="qz hit"><span class="lbl">原文</span>${{esc(r.原文)}}</div>
        <div class="q"><span class="lbl">边界</span>${{esc(r.边界)}}</div>
        ${{s?`<details><summary style="cursor:pointer;font-size:12.5px;color:#8a4b2a">看所在片段（${{esc(r.锚点)}}）</summary>
          <div class="qz">${{hl(s.文本, r.原文)}}</div></details>`:''}}
      </div>`;
    }}).join('');
  }} else if (curCard==='topics') {{
    box.innerHTML = D.topics.map(t=>{{
      const layers = (t.层||[]).map(l=>{{
        const s = segOf(t.码, l.锚点);
        return `<div style="margin:9px 0 0 0">
          <div style="font-size:13px;font-weight:600;color:#6b4f2a">${{esc(l.题)}}</div>
          <div class="q">${{esc(l.文)}}</div>
          ${{l.引?`<div class="qz hit"><span class="lbl">原文</span>${{esc(l.引)}}</div>`:''}}
          ${{s?`<details><summary style="cursor:pointer;font-size:12px;color:#8a4b2a">${{esc(l.锚点)}}·${{esc(s.篇)}}</summary>
            <div class="qz">${{hl(s.文本, l.引||'')}}</div></details>`:''}}
        </div>`;
      }}).join('');
      const mir = (t.对照||[]).map(c=>`<div style="margin-top:9px;padding:9px 11px;background:#f7f2e6;border-radius:4px">
        <div style="font-size:12.5px;font-weight:600;color:#7a5a33;white-space:pre-line">${{esc(c.题)}}</div>
        <div class="q"><span class="lbl">甲</span>${{esc(c.甲减)}}</div>
        <div class="q"><span class="lbl">乙</span>${{esc(c.乙加)}}</div>
        <div class="q"><span class="lbl">辨</span>${{esc(c.辨)}}</div></div>`).join('');
      return `<div class="card">
        <div class="t">${{esc(t.主题)}} <span class="tag">${{esc(t.类型)}}</span> <span class="tag">${{esc(t.id)}}</span></div>
        <div class="q" style="color:#7a6a58">${{esc(t.副)}}</div>
        <div style="font-size:12.5px;color:#8b7b68;margin:8px 0 2px">
          为什么难读：${{esc(t.为什么难读)}}</div>
        <div style="font-size:12.5px;margin:8px 0;color:#6b4a2a">
          依据 ${{t.依据段数}} 段 · 跨 ${{t.覆盖篇数}} 篇 · 跨度 ${{t.跨度}} · 占全书段 ${{t.覆盖段比}}%</div>
        ${{layers}}
        ${{mir?`<div style="margin-top:12px">${{mir}}</div>`:''}}
        <div class="qz" style="margin-top:11px"><span class="lbl">结论</span>${{esc(t.结论)}}</div>
      </div>`;
    }}).join('');
  }} else {{
    box.innerHTML = D.mirrors.map(m=>`<div class="card">
      <div class="t">${{esc(m.书)}}｜${{esc(m.主题)}} <span class="tag">${{esc(m.id)}}</span></div>
      <div class="q"><span class="lbl">你大概会读成</span>${{esc(m['你大概会读成'])}}</div>
      <div class="q" style="color:#8a4b2a"><span class="lbl">原文另有一处</span>${{esc(m['原文另有一处相反说法'])}}</div>
      <div class="qz"><span class="lbl">甲</span>${{esc(m.甲引)}}</div>
      <div class="qz"><span class="lbl">乙</span>${{esc(m.乙引)}}</div>
      <div class="q"><span class="lbl">差别在哪</span>${{esc(m['差别在哪'])}}</div>
    </div>`).join('');
  }}
}}

/* ---------- 原文溯源 ---------- */
function renderTrace(){{
  const code = 'ZHS';
  const m = D.segs[code] || {{}};
  const ids = Object.keys(m).filter(k=>m[k].篇序>0);
  /* 建立「锚点 → 引用它的卡」索引 */
  const idx = {{}};
  D.topics.filter(t=>t.码===code).forEach(t=>{{
    (t.层||[]).forEach(l=>{{ (idx[l.锚点]=idx[l.锚点]||[]).push(t.主题); }});
    (t.对照||[]).forEach(c=>{{
      [c.甲锚,c.乙锚].forEach(a=>{{ if(a)(idx[a]=idx[a]||[]).push(t.主题); }});
    }});
  }});
  D.mirrors.filter(x=>x.书==='朝花夕拾').forEach(x=>{{
    [x.甲锚,x.乙锚].forEach(a=>{{ if(a)(idx[a]=idx[a]||[]).push(x.主题); }});
  }});
  /* 支持从任意段落反查：输入篇名/关键词，看它被谁引用 */
  let box = `<div class="note">
    共 ${{Object.keys(idx).length}} 段被卡片引用，占《朝花夕拾》正文 ${{ids.length}} 段的
    ${{(Object.keys(idx).length/ids.length*100).toFixed(1)}}%。下方可筛选：只看被引用的段，或搜索任意关键词。</div>
    <div style="margin-bottom:12px">
      <input id="q" placeholder="输入篇名或关键词，如「父亲」「无常」"
       style="padding:6px 10px;border:1px solid #d9cfbe;border-radius:4px;width:280px;font-size:13px;font-family:inherit">
      <label style="font-size:12.5px;color:#6b5a46;margin-left:10px">
        <input type="checkbox" id="onlycited" checked> 只看被卡片引用的段</label>
    </div><div id="tracebox"></div>`;
  document.getElementById('trace').innerHTML = box;

  function draw(){{
    const kw = (document.getElementById('q').value||'').trim();
    const only = document.getElementById('onlycited').checked;
    let list = ids;
    if (only) list = list.filter(k=>idx[k]);
    if (kw) list = list.filter(k=>m[k].篇.includes(kw) || m[k].文本.includes(kw));
    const out = list.slice(0, 40).map(k=>{{
      const s = m[k];
      const cited = idx[k] ? `<div style="margin-top:6px;font-size:12px;color:#8a4b2a">
        被以下卡片引用：${{[...new Set(idx[k])].map(esc).join('、')}}</div>`
        : `<div style="margin-top:6px;font-size:12px;color:#b0a292">暂无卡片引用此段</div>`;
      return `<div class="card">
        <div class="t" style="font-size:13.5px">${{esc(s.篇)}} · ${{esc(k)}} </div>
        <div class="q">${{esc(s.文本)}}</div>${{cited}}</div>`;
    }});
    document.getElementById('tracebox').innerHTML =
      (list.length? out.join('') : '<div class="warn">没有匹配的段落。</div>')
      + (list.length>40? `<div class="note">仅显示前 40 条，共 ${{list.length}} 条命中。</div>`:'');
  }}
  document.getElementById('q').oninput = draw;
  document.getElementById('onlycited').onchange = draw;
  draw();
}}

/* ---------- 候选卡层 ---------- */
let curCand = D.cand.types[0] || '';
function renderCandTabs(){{
  document.getElementById('candtabs').innerHTML = D.cand.types.map(t=>{{
    const n = Object.values(D.cand.bys).reduce((a,b)=>a+(b[t]||0),0);
    const m = D.cand.meta[t] || ['中','需人筛',''];
    return `<div class="tab ${{t===curCand?'on':''}}" data-k="${{t}}"
      title="${{esc(m[2])}}">${{esc(t)}} ${{n}}<span style="opacity:.6">·${{esc(m[0])}}</span></div>`;
  }}).join('');
  document.querySelectorAll('#candtabs .tab').forEach(el=>el.onclick=()=>{{
    curCand = el.dataset.k; renderCandTabs(); renderCandBody();
  }});
  // 精度汇总：三类分开报，不合并
  const g = D.cand.grade || {{}};
  document.getElementById('gradebox').innerHTML = `<table><thead><tr>
    <th>候选分级</th><th>条数</th><th>含义</th></tr></thead><tbody>
    <tr><td><span class="tag p3">可直接用</span></td><td class="ok">${{g['可直接用']||0}}</td>
      <td>形态确定，机器抽即正确；只需补一句「它是做什么的」</td></tr>
    <tr><td><span class="tag p7">需人筛</span></td><td>${{g['需人筛']||0}}</td>
      <td>形态对但语义要人过一遍，约一成需剔除</td></tr>
    <tr><td><span class="tag">仅为定位器</span></td><td class="no">${{g['仅为定位器']||0}}</td>
      <td>只告诉你「去哪找」，内容本身还得人写，<b>不算资产</b></td></tr>
    </tbody></table>`;
}}
function renderCandBody(){{
  const books = Object.keys(D.cand.bys).filter(b=>(D.cand.bys[b][curCand]||0)>0);
  const m = D.cand.meta[curCand] || ['中','需人筛',''];
  let h = `<div class="note">「${{esc(curCand)}}」共 ${{books.reduce((a,b)=>a+D.cand.bys[b][curCand],0)}} 条，
    分布在 ${{books.length}} 本书 · <b>${{esc(m[1])}}</b>：${{esc(m[2])}}</div>`;
  h += '<table><thead><tr><th>书</th><th>条数</th><th>该类型在本类的分项</th></tr></thead><tbody>';
  books.sort((a,b)=>D.cand.bys[b][curCand]-D.cand.bys[a][curCand]).forEach(b=>{{
    const parts = Object.entries(D.cand.bys[b]).map(([k,v])=>`${{k}} ${{v}}`).join(' · ');
    h += `<tr><td>${{esc(b)}}</td>
      <td><span class="bar hot" style="width:${{Math.round(D.cand.bys[b][curCand]/Math.max(...books.map(x=>D.cand.bys[x][curCand]))*110)}}px"></span>
        ${{D.cand.bys[b][curCand]}}</td>
      <td style="font-size:12px;color:#7a6a58">${{esc(parts)}}</td></tr>`;
  }});
  h += '</tbody></table>';
  const sp = D.cand.sample[curCand] || [];
  if (sp.length) {{
    h += `<div class="note" style="margin-top:18px">抽两条看抽取器准不准（原文都已在正文逐字校验过）：</div>`;
    h += sp.map(s=>`<div class="card">
      <div class="t" style="font-size:13.5px">${{esc(s.书)}} · ${{esc(s.锚点)}}</div>
      <div class="qz hit"><span class="lbl">原文</span>${{esc(s.原文)}}</div>
      <div class="q" style="color:#8b7b68"><span class="lbl">还缺</span>${{esc((s.待补||[]).join(' / '))}}</div>
    </div>`).join('');
  }}
  document.getElementById('candbody').innerHTML = h;
}}

renderTabs(); renderTable(); renderMatrix(); renderQuant();
renderCandTabs(); renderCandBody();
renderCTabs(); renderCards(); renderTrace();
</script></body></html>'''

    dest = f'{BASE}/书库平台看板.html'
    io.open(dest, 'w', encoding='utf-8').write(html_doc)
    print('写出', os.path.relpath(dest, P.ROOT), len(html_doc), '字节')


if __name__ == '__main__':
    main()

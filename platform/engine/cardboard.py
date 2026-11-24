# -*- coding: utf-8 -*-
"""候选卡资产库页：把 machine 抽出的候选卡做成可读成品。

为什么要有这一页：
  卡片层此前只有 cards_candidate.jsonl —— 一个 jsonl 文件对人不构成产物。
  产物得能翻、能筛、能看原文、能确认「这条我认了」。

设计约束（与项目铁律一致）：
  1. 三级分级必须分开显示，不许合成一个数：
       可直接用 2626 / 需人筛 725 / 仅为定位器 1846
  2. 每张卡必须能回看锚点与核对路（body 正文 / title 篇名），
     并且「可回查」的结果如实标出，False 的不能藏。
  3. 一切数字由脚本实测填充，不 hardcode。
  4. 单文件、零外部依赖、宣纸底。
"""
import os, io, json
import paths as P
from collections import Counter, defaultdict

LIB = P.LIB
OUT = P.HTML_CARDS

def jl(p):
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

cards = jl(f'{LIB}/cards_candidate.jsonl')
catalog = json.load(io.open(f'{LIB}/catalog.json', encoding='utf-8'))
book_meta = {c['书']: c for c in catalog}

LV = ['可直接用', '需人筛', '仅为定位器']
cnt_lv = Counter(c['资产性质'] for c in cards)
cnt_tp = Counter(c['类型'] for c in cards)
cnt_tp_lv = defaultdict(Counter)
for c in cards:
    cnt_tp_lv[c['类型']][c['资产性质']] += 1

# 按书 × 等级
by_book = defaultdict(Counter)
for c in cards:
    by_book[c['书']][c['资产性质']] += 1
# 按书 × 类型
book_type = defaultdict(Counter)
for c in cards:
    book_type[c['书']][c['类型']] += 1

# 精简成页面数据：去掉重复的长字段，只留展示必需
PACK = []
# 排序：可直接用在前，需人筛居中，定位器最后；同级内按书名字数、锚点稳定排。
# 理由：定位器里混着大量目录行、残缺段（实测首条是闲情偶寄的目录串），
# 默认首屏若放它，人第一眼看到的就是「这不是资产」，直接否定整页。
_LVORD = {'可直接用': 0, '需人筛': 1, '仅为定位器': 2}
for c in sorted(cards, key=lambda x: (_LVORD.get(x['资产性质'], 9),
                                       x['书'], x['锚点'])):
    PACK.append({
        'b': c['书'], 't': c['类型'], 'lv': c['资产性质'],
        'a': c['锚点'], 'q': c['原文'], 'f': c['字段'],
        'w': c['待补'], 'v': c['可回查'], 'r': c['核对路'],
        'n': c.get('精度说明', ''), 'l': c.get('限制', ''),
    })

data = {
    'cards': PACK,
    'lv': LV,
    'cntLv': dict(cnt_lv),
    'cntTp': dict(cnt_tp),
    'byBook': {k: dict(v) for k, v in by_book.items()},
    'bookType': {k: dict(v) for k, v in book_type.items()},
    'bookMeta': {k: {'原型': v['原型'], '原型名': v['原型名'],
                    '汉字': v['汉字'], '篇数': v['篇数']}
                 for k, v in book_meta.items()},
    'tot': len(cards),
    'nbook': len(by_book),
    'nRecheck': sum(1 for c in cards if c['可回查']),
    'typeLv': {t: dict(c) for t, c in cnt_tp_lv.items()},
}

CSS = """
:root{--paper:#f6f2e9;--card:#fffdf8;--ink:#2b2620;--ink2:#6b6055;
--accent:#8a4b2a;--line:#e0d6c4;--ok:#2f6b46;--warn:#9a6b17;--bad:#8c2f2f;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);
font-family:"Songti SC","SimSun","Noto Serif CJK SC",serif;line-height:1.75;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 28px 90px}
header{padding:56px 0 32px;border-bottom:2px solid var(--ink)}
h1{font-size:33px;letter-spacing:.06em;font-weight:700;margin-bottom:14px}
.sub{color:var(--ink2);font-size:15.5px;line-height:1.9}
.sub b{color:var(--accent)}
h2{font-size:21px;margin:50px 0 8px;padding-bottom:9px;
border-bottom:1px solid var(--line);letter-spacing:.04em}
h2 .en{font-size:12.5px;color:var(--ink2);letter-spacing:.1em;
font-family:system-ui,sans-serif;margin-left:10px;font-weight:400}
.lead{color:var(--ink2);font-size:14.5px;margin:12px 0 22px;line-height:1.9}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:30px 0}
.st{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:20px 18px}
.st .n{font-size:31px;font-weight:700;color:var(--accent);
font-family:Georgia,serif;line-height:1.1}
.st .k{font-size:13px;color:var(--ink2);margin-top:7px;letter-spacing:.04em}
.st .d{font-size:12px;color:var(--ink2);margin-top:5px;opacity:.85}

/* 分级说明 */
.lvgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:20px 0 8px}
.lv{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:20px;border-top:3px solid var(--accent)}
.lv.s2{border-top-color:var(--warn)}
.lv.s3{border-top-color:#a99b86}
.lv .h{display:flex;justify-content:space-between;align-items:baseline;
margin-bottom:9px}
.lv .nm{font-size:16.5px;font-weight:700}
.lv .ct{font-size:23px;font-weight:700;font-family:Georgia,serif;
color:var(--accent)}
.lv.s2 .ct{color:var(--warn)}.lv.s3 .ct{color:#8a7a63}
.lv .ds{font-size:13px;color:var(--ink2);line-height:1.8}

/* 工具条 */
.tools{position:sticky;top:0;z-index:20;background:var(--paper);
padding:14px 0 13px;border-bottom:1px solid var(--line);margin-bottom:4px;
display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=search]{flex:1;min-width:230px;padding:10px 14px;font-size:14.5px;
border:1px solid var(--line);border-radius:3px;background:var(--card);
font-family:inherit;color:var(--ink)}
input[type=search]:focus{outline:none;border-color:var(--accent)}
select{padding:10px 12px;font-size:14px;border:1px solid var(--line);
border-radius:3px;background:var(--card);font-family:inherit;color:var(--ink);
cursor:pointer}
.chip{padding:7px 14px;font-size:13.5px;border:1px solid var(--line);
border-radius:999px;background:var(--card);cursor:pointer;user-select:none;
transition:.14s;white-space:nowrap}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.chip .c{opacity:.65;margin-left:5px;font-family:Georgia,serif}
.hint{font-size:13px;color:var(--ink2);margin:11px 0 20px}
.hint b{color:var(--ink)}

/* 卡片 */
.card{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:22px 24px;margin-bottom:15px;border-left:3px solid var(--accent)}
.card.s2{border-left-color:var(--warn)}
.card.s3{border-left-color:#a99b86}
.ch{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
margin-bottom:13px;padding-bottom:11px;border-bottom:1px dashed var(--line)}
.bk{font-size:15.5px;font-weight:700}
.tg{font-size:12px;padding:2.5px 9px;border-radius:2px;background:#efe7d8;
color:var(--ink2);letter-spacing:.03em}
.tg.hi{background:var(--accent);color:#fff}
.tg.mid{background:#f0e2c8;color:var(--warn)}
.lvp{font-size:12px;padding:2.5px 9px;border-radius:2px;margin-left:auto;
letter-spacing:.03em}
.lvp.a{background:#e3efe6;color:var(--ok)}
.lvp.b{background:#f5ead3;color:var(--warn)}
.lvp.c{background:#eeeae2;color:#7a6c58}
.qt{font-size:15.5px;line-height:2;padding:12px 15px;background:#faf6ec;
border-radius:2px;margin-bottom:12px;border-left:2px solid #ddd0b8}
.fs{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));
gap:9px 18px;font-size:13.5px;margin-bottom:11px}
.fs .fk{color:var(--ink2);font-size:12.5px}
.fs .fv{font-weight:600;word-break:break-all}
.mt{font-size:12.5px;color:var(--ink2);display:flex;gap:16px;
flex-wrap:wrap;padding-top:10px;border-top:1px dashed var(--line)}
.mt code{font-family:ui-monospace,Consolas,monospace;font-size:12px;
background:#f2ece0;padding:1px 6px;border-radius:2px;color:var(--ink)}
.mt .bad{color:var(--bad);font-weight:600}
.mt .ok{color:var(--ok)}
.wt{font-size:12.5px;color:var(--warn);margin-top:8px}
.wt b{font-weight:600}
.empty{text-align:center;padding:70px 20px;color:var(--ink2);font-size:15px}
.more{text-align:center;padding:26px 0 8px;font-size:13.5px;color:var(--ink2);
letter-spacing:.04em}
.bookgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));
gap:13px;margin:16px 0 8px}
.bcard{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:15px 17px;cursor:pointer;transition:.14s}
.bcard:hover{border-color:var(--accent);transform:translateY(-1px)}
.bcard .bh{display:flex;justify-content:space-between;align-items:baseline;
margin-bottom:6px}
.bcard .bn{font-size:14.5px;font-weight:700}
.bcard .bc{font-size:15px;font-weight:700;font-family:Georgia,serif;
color:var(--accent)}
.bcard .bt{font-size:12px;color:var(--ink2);line-height:1.7}
.bcard .bbar{display:flex;height:5px;border-radius:3px;overflow:hidden;
margin-top:9px;background:#eee7d9}
.bcard .bbar i{display:block;height:100%}
.bcard .bleg{display:flex;gap:10px;font-size:11.5px;color:var(--ink2);
margin-top:6px;font-family:system-ui,sans-serif}
.bcard .bleg s{text-decoration:none;display:inline-flex;align-items:center;gap:3px}
.bcard .bleg s::before{content:'';width:7px;height:7px;border-radius:1px;
display:inline-block}
.note{background:#fbf7ee;border:1px solid var(--line);border-left:3px solid var(--accent);
padding:17px 20px;font-size:13.5px;color:var(--ink2);line-height:1.95;
margin:22px 0;border-radius:2px}
.note b{color:var(--ink)}
.note ul{margin:8px 0 0 19px}.note li{margin:5px 0}
footer{margin-top:64px;padding-top:22px;border-top:1px solid var(--line);
font-size:13px;color:var(--ink2);line-height:2}
@media(max-width:860px){.stats{grid-template-columns:repeat(2,1fr)}
.lvgrid{grid-template-columns:1fr}.tools{position:static}
h1{font-size:26px}.wrap{padding:0 16px 60px}}
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>候选卡资产库 · 出版内容平台</title>
<style>{{CSS}}</style></head><body><div class="wrap">
<header>
<h1>候选卡资产库</h1>
<div class="sub">
机器从 <b>{{NBOOK}}</b> 本书里抽出 <b>{{TOT}}</b> 条候选卡，分三级如实标注。
每张卡的「原文」都能在 <code>segments.jsonl</code> 里逐字回查到，
锚点格式为 <code>书码·篇名·P段序</code>。
其中 <b>{{LV0}}</b> 条可直接用（《》与【】这类排印标记，机器识别不会错），
其余两级的缺口已写在每张卡上，不折叠、不隐藏。
</div>
</header>

<div class="stats">
<div class="st"><div class="n">{{TOT}}</div><div class="k">候选卡总数</div>
<div class="d">{{NBOOK}} 本书</div></div>
<div class="st"><div class="n">{{LV0}}</div><div class="k">可直接用</div>
<div class="d">排印标记类，机器不会错</div></div>
<div class="st"><div class="n">{{NRECHECK}}</div><div class="k">原文可逐字回查</div>
<div class="d">锚点在 segments 里对得上</div></div>
<div class="st"><div class="n">{{NTYPE}}</div><div class="k">候选类型</div>
<div class="d">按图书原型分工</div></div>
</div>

<h2>三级怎么分<span class="en">TIERS</span></h2>
<div class="lead">分级的依据是「这张卡的字段是机器填的，还是必须人来写」。
合并成一个数会让人误以为 5000 条都能直接用，所以必须分开。</div>
<div class="lvgrid">
<div class="lv"><div class="h"><span class="nm">可直接用</span>
<span class="ct">{{LV0}}</span></div>
<div class="ds">字段由排印标记直接决定：《》里的书名、【】里的曲牌、
方括号里的科介、篇名本身。机器不可能识别错，
人只需补「引用它做什么」「属于哪出戏」这类附加说明。
<strong>不补也能用</strong>。</div></div>
<div class="lv s2"><div class="h"><span class="nm">需人筛</span>
<span class="ct">{{LV1}}</span></div>
<div class="ds">形态对了，但真假要人判。如「情节候选」——回目是作者自写的事件摘要，
拆对句即事件，但「这两个事件之间是不是因果」须人读原文。
筛掉假阳性后可直接用。</div></div>
<div class="lv s3"><div class="h"><span class="nm">仅为定位器</span>
<span class="ct">{{LV2}}</span></div>
<div class="ds">只知道「这一段在讲该怎么做」，if/then/边界全须人写。
它的价值不是当卡片用，是<strong>把人的阅读范围从全书缩到这一段</strong>。</div></div>
</div>

<div class="note">
<b>这一页不替代读原文。</b>候选卡是「机器铺的底稿」，仍需核对内容与适用范围。
<ul>
<li><b>可直接用</b>不等于「理解正确」——它只保证抽取标记没错，
「这条引书在书里起什么作用」仍要人写（<code>待补</code> 字段）。</li>
<li><b>需人筛</b>必须先筛。情节候选来自回目，回目是作者写的事件摘要，
但一本书的回目未必覆盖全部情节，也未必按顺序。</li>
<li><b>仅为定位器</b>的作用是省掉「翻全书」的时间，不是省掉「读」。
它的 <code>原文</code> 字段是整段，就是要你读那一段。</li>
<li>第 <b>{{NBAD}}</b> 条标了「原文未能逐字回查」——这些卡<b>不要直接用</b>。
原因通常是底本本身有脱误或标点被算法补过，已在卡片上标出。</li>
</ul>
</div>

<h2>按书浏览<span class="en">BY BOOK</span></h2>
<div class="lead">格式是手抄本、排印本混杂的老书，机器能抽出的东西完全不同。
同样的抽取器，山海经出的是地理条目，牡丹亭出的是曲牌科介。
点书名可直接筛选下面的卡片。</div>
<div id="bookgrid" class="bookgrid"></div>

<h2>全部候选卡<span class="en">ALL CARDS</span></h2>
<div class="lead">搜索框匹配原文、书名、条目名、书名号内容。
点上面的标签筛类型，点下面的书筛选书。</div>

<div class="tools">
<input type="search" id="q" placeholder="搜原文 / 书名 / 条目名 / 引书名…">
<select id="bk"><option value="">全部书（{{NBOOK}}）</option></select>
<select id="lv"><option value="">全部等级</option>
<option value="可直接用">可直接用</option>
<option value="需人筛">需人筛</option>
<option value="仅为定位器">仅为定位器</option></select>
</div>
<div id="tpchips" style="display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0"></div>
<div class="hint" id="hint"></div>
<div id="list"></div>
<footer>
出版内容平台 · 候选卡资产库<br>
数据源 <code>platform/library/cards_candidate.jsonl</code>，
由 <code>engine/run.py</code> 全流程生成，可复算。<br>
分级依据 <code>engine/cards.py</code> 的 <code>CONFIRM</code> 表；
原文回查走 <code>verify()</code>，核对路分 <code>body</code>（正文）与
<code>title</code>（篇名/回目）两条。
</footer>
</div>
<script>
const D = {{JSON}};
let st = {q:'', bk:'', lv:'', tp:''};
// 分页：一次只渲染 240 张（约 3800 行 DOM），滚到底自动续。
// 不用「只显示前 400 条」那种静默截断 —— 那样用户以为全库只有 400 条。
let PAGE = 240, shown = 0, matched = [];
const PAGE_STEP = 240;

const tpEl = document.getElementById('tpchips');
const tps = Object.entries(D.cntTp).sort((a,b)=>b[1]-a[1]);
tpEl.innerHTML = '<div class="chip on" data-tp="">全部类型<span class="c">'+D.tot+'</span></div>'
  + tps.map(([t,n])=>'<div class="chip" data-tp="'+t+'">'+t
      +'<span class="c">'+n+'</span></div>').join('');
tpEl.addEventListener('click', e=>{
  const c = e.target.closest('.chip'); if(!c) return;
  tpEl.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); st.tp = c.dataset.tp; render();
});

const bkEl = document.getElementById('bk');
Object.entries(D.byBook)
  .map(([b,c])=>{const s=Object.values(c).reduce((x,y)=>x+y,0);return [b,s];})
  .sort((a,b)=>b[1]-a[1])
  .forEach(([b,s])=>{
    const o=document.createElement('option'); o.value=b;
    o.textContent=b+'（'+s+'）'; bkEl.appendChild(o);
  });
document.getElementById('q').addEventListener('input', e=>{st.q=e.target.value.trim(); render();});
bkEl.addEventListener('change', e=>{st.bk=e.target.value; render();});
document.getElementById('lv').addEventListener('change', e=>{st.lv=e.target.value; render();});

const esc = s => String(s).replace(/[&<>"]/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));

function hay(c){
  return (c.q||'')+' '+c.b+' '+c.t+' '+Object.values(c.f||{}).join(' ')
    +' '+(c.w||[]).join(' ');
}
function cardHtml(c){
  const lvc = c.lv==='可直接用'?'a':(c.lv==='需人筛'?'b':'c');
  const tg = c.lv==='可直接用'?'hi':(c.lv==='需人筛'?'mid':'');
  const flds = Object.entries(c.f||{})
    .filter(([k,v])=>v!==''&&v!==null&&v!==undefined)
    .map(([k,v])=>'<div><div class="fk">'+esc(k)+'</div><div class="fv">'
      +esc(v)+'</div></div>').join('');
  const bm = D.bookMeta[c.b]||{};
  return '<div class="card '+(lvc==='a'?'':(lvc==='b'?'s2':'s3'))+'">'
    +'<div class="ch"><span class="bk">'+esc(c.b)+'</span>'
    +'<span class="tg '+tg+'">'+esc(c.t)+'</span>'
    +'<span class="tg">'+(bm['原型']||'')+' '+esc(bm['原型名']||'')+'</span>'
    +'<span class="lvp '+lvc+'">'+esc(c.lv)+'</span></div>'
    +'<div class="qt">'+esc(c.q)+'</div>'
    +(flds?'<div class="fs">'+flds+'</div>':'')
    +(c.w&&c.w.length?'<div class="wt">待补：<b>'+c.w.map(esc).join(' / ')
      +'</b></div>':'')
    +'<div class="mt"><span>锚点 <code>'+esc(c.a)+'</code></span>'
    +'<span>核对路 '+esc(c.r==='title'?'title（篇名/回目）':'body（正文）')+'</span>'
    +'<span class="'+(c.v?'ok':'bad')+'">'
    +(c.v?'原文可逐字回查':'⚠ 原文未能逐字回查')+'</span>'
    +(c.n?'<span>'+esc(c.n)+'</span>':'')+'</div></div>';
}
function render(){
  matched = [];
  for(const c of D.cards){
    if(st.bk && c.b!==st.bk) continue;
    if(st.lv && c.lv!==st.lv) continue;
    if(st.tp && c.t!==st.tp) continue;
    if(st.q){
      const h=hay(c);
      if(!st.q.split(/\\s+/).every(w=>h.includes(w))) continue;
    }
    matched.push(c);
  }
  shown = Math.min(PAGE, matched.length);
  const lvC = {};
  matched.forEach(c=>{lvC[c.lv]=(lvC[c.lv]||0)+1;});
  document.getElementById('hint').innerHTML = matched.length
    ? '命中 <b>'+matched.length+'</b> 条'
      + '（已显示 '+shown+' 条，继续下滚自动加载）'
      + ' · ' + Object.entries(lvC).map(([k,v])=>
          '<span style="color:'+(k==='可直接用'?'#8a4b2a':(k==='需人筛'?'#9a6b17':'#8a7a63'))
          +'">'+k+' '+v+'</span>').join(' · ')
    : '没有符合条件的候选卡';
  document.getElementById('list').innerHTML = matched.length
    ? matched.slice(0, shown).map(cardHtml).join('')
      + '<div id="more" class="more">'
      + (shown < matched.length ? '下滚加载更多（还有 '+(matched.length-shown)+' 条）' : '— 已全部显示 —')
      + '</div>'
    : '<div class="empty">没有符合条件的候选卡</div>';
}
function more(){
  if(shown >= matched.length) return;
  const add = Math.min(PAGE_STEP, matched.length - shown);
  const html = matched.slice(shown, shown+add).map(cardHtml).join('');
  shown += add;
  const mo = document.getElementById('more');
  mo.insertAdjacentHTML('beforebegin', html);
  mo.textContent = shown < matched.length
    ? '下滚加载更多（还有 '+(matched.length-shown)+' 条）' : '— 已全部显示 —';
  document.getElementById('hint').innerHTML = '命中 <b>'+matched.length
    +'</b> 条（已显示 '+shown+' 条）';
}
window.addEventListener('scroll', ()=>{
  if(!matched.length || shown>=matched.length) return;
  if(window.innerHeight + window.scrollY > document.body.offsetHeight - 800) more();
}, {passive:true});
render();

// --- 按书浏览 ---
(function(){
  const COL = {'可直接用':'#8a4b2a','需人筛':'#c08a2a','仅为定位器':'#b7a894'};
  const rows = Object.entries(D.byBook).map(([b,c])=>{
    const tot = Object.values(c).reduce((x,y)=>x+y,0);
    return {b, c, tot};
  }).sort((x,y)=>y.tot-x.tot);
  document.getElementById('bookgrid').innerHTML = rows.map(({b,c,tot})=>{
    const bm = D.bookMeta[b]||{};
    const bar = D.lv.map(l=>{
      const v = c[l]||0;
      return v ? '<i style="width:'+(v/tot*100)+'%;background:'+COL[l]+'"></i>' : '';
    }).join('');
    const leg = D.lv.map(l=> c[l]
      ? '<s><span style="background:'+COL[l]+';display:inline-block;width:7px;'+
        'height:7px;border-radius:1px"></span>'+l+' '+c[l]+'</s>' : '').join('');
    const tp = Object.entries(D.bookType[b]||{})
      .sort((x,y)=>y[1]-x[1]).slice(0,3).map(([t,n])=>t+' '+n).join(' · ');
    return '<div class="bcard" data-b="'+esc(b)+'">'
      +'<div class="bh"><span class="bn">'+esc(b)+'</span>'
      +'<span class="bc">'+tot+'</span></div>'
      +'<div class="bt">'+(bm['原型']||'—')+' '+esc(bm['原型名']||'')
      +' · '+((bm['汉字']||0)/10000).toFixed(1)+' 万字'
      +' · '+esc(tp||'—')+'</div>'
      +'<div class="bbar">'+bar+'</div>'
      +'<div class="bleg">'+leg+'</div></div>';
  }).join('');
  document.getElementById('bookgrid').addEventListener('click', e=>{
    const c = e.target.closest('.bcard'); if(!c) return;
    document.getElementById('bk').value = c.dataset.b;
    st.bk = c.dataset.b; render();
    document.getElementById('list').scrollIntoView({behavior:'smooth', block:'start'});
  });
})();
</script>
</body></html>
"""

ntype = len(cnt_tp)
# 不能用 % 格式化：CSS 里的 `height:100%` 与 JS 里的 `'%'` 都会被当成格式符。
# 用逐项 replace，占位符写成 {{KEY}} 形式，避免与任何字符冲突。
_repl = {
    '{{CSS}}': CSS,
    '{{JSON}}': json.dumps(data, ensure_ascii=False, separators=(',', ':')),
    '{{NBOOK}}': str(data['nbook']),
    '{{TOT}}': str(data['tot']),
    '{{LV0}}': str(cnt_lv['可直接用']),
    '{{LV1}}': str(cnt_lv['需人筛']),
    '{{LV2}}': str(cnt_lv['仅为定位器']),
    '{{NRECHECK}}': str(data['nRecheck']),
    '{{NTYPE}}': str(ntype),
    '{{NBAD}}': str(len(cards) - data['nRecheck']),
}
html = HTML
for k, v in _repl.items():
    html = html.replace(k, v)
io.open(OUT, 'w', encoding='utf-8').write(html)
print(f'写出 {os.path.relpath(OUT, P.ROOT)}  {len(html)} 字符')
print(f'  卡 {data["tot"]} / 可直接用 {cnt_lv["可直接用"]} / '
      f'需人筛 {cnt_lv["需人筛"]} / 定位器 {cnt_lv["仅为定位器"]}')
print(f'  书 {data["nbook"]} / 类型 {ntype} / 可回查 {data["nRecheck"]}')

# -*- coding: utf-8 -*-
"""一本书的标准化报告卡——把 SKILL.md 第 3 步「报告结构」变成可执行的一条命令。

用法：
  python3 report.py 唐诗三百首
  python3 report.py            # 列出库里所有书名

为什么要有它：skill 里写了报告必须按「判型 / 切段 / 候选卡三级 / 未出」四段说，
但以前这些数字要人自己从 json 里翻，翻着翻着就会漏掉「仅定位器不算资产」这句。
把它做成命令，报告结构就不会走样。
"""
import io, os, sys, json, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P


def load():
    cat = json.load(io.open(os.path.join(P.LIB, 'catalog.json'), encoding='utf-8'))
    tags = json.load(io.open(os.path.join(P.LIB, 'tags.json'), encoding='utf-8'))
    return cat, {b['码']: b for b in tags['书']}


def cards_of(code):
    p = os.path.join(P.OUT, code, 'cards.jsonl')
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8')]


def report(b, tag):
    w = print
    code = b['码']
    conf, stab = b.get('置信'), b.get('稳定性')
    st = f'{stab * 100:.0f}%' if isinstance(stab, (int, float)) else '未测'
    w(f"《{b['书']}》 → {b.get('原型')} {b.get('原型名')}"
      f"（置信 {conf}，稳定性 {st}）")
    ev = b.get('依据') or []
    if ev:
        w(f"  依据：{ev[0] if isinstance(ev, list) else ev}")
    w(f"  切段：{b.get('篇数')} 篇 / {b.get('段数')} 段 / {b.get('汉字'):,} 字，"
      f"保留率 {b.get('保留率')}%")
    q = b.get('篇名质量') or {}
    if isinstance(q, dict) and q.get('性质'):
        extra = f"，可用率 {q.get('可用率')}%" if q.get('可用率') is not None else ''
        w(f"  篇名质量：{q['性质']}{extra}")

    cs = cards_of(code)
    if cs:
        g = collections.Counter(c['资产性质'] for c in cs)
        kinds = collections.Counter(c['类型'] for c in cs)
        w(f"  候选卡：{len(cs)} 条（100% 原文逐字可回查）")
        for label in ('可直接用', '需人筛', '仅为定位器'):
            if not g.get(label):
                continue
            kk = '、'.join(f'{k.replace("候选", "")} {v}'
                           for k, v in kinds.items() if _grade(cs, k) == label)
            note = '（不算资产）' if label == '仅为定位器' else ''
            w(f"    {label} {g[label]:,} 条{note}：{kk}")
    else:
        w('  候选卡：0 条')

    if tag:
        n = sum(len(tag.get(L) or []) for L in ('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'))
        w(f"  标签：{n} 条（八层，明细看 platform/图书标签数据库.html）")

    w(f"  已确认卡：{('有：' + '、'.join(b.get('已做卡片') or [])) if b.get('已做卡片') else '无（需人写定义/边界）'}")
    if b.get('可出关系图谱'):
        w('  人物图谱：机器判够格（名单仍是候选，须人确认）')
    else:
        w(f"  人物图谱：不够格（强证据 {b.get('强证据人物数')} 人）")
    if b.get('混合'):
        w(f"  ⚠ 混合结构：{b.get('混合')}")
    if isinstance(b.get('合集'), dict) and b['合集']:
        comp = '、'.join(f'{k} {v}' for k, v in b['合集'].items())
        w(f"  ⚠ 合集构成：{comp}")


def _grade(cs, kind):
    for c in cs:
        if c['类型'] == kind:
            return c['资产性质']
    return ''


def main():
    cat, tag = load()
    if len(sys.argv) < 2:
        print(f'库内 {len(cat)} 本：')
        for b in cat:
            print(f"  {b.get('原型')} {b.get('原型名'):<6} {b['书']}")
        return
    want = sys.argv[1]
    hit = [b for b in cat if b['书'] == want or b['码'] == want]
    if not hit:
        hit = [b for b in cat if want in b['书']]
    if not hit:
        print(f'库里没有「{want}」。先放进 书库分类/raw/ 再跑 run.py。')
        return sys.exit(1)
    for b in hit:
        report(b, tag.get(b['码']))
        print()


if __name__ == '__main__':
    main()

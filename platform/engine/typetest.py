# -*- coding: utf-8 -*-
"""类型覆盖测试台：检验判型规则对「非既有九类」的响应。

与 pipeline 的区别：
  pipeline 跑真实书库，产出资产。
  本脚本跑测试集，只做一件事 —— 记录 system 对每类输入的反应。

三件必须同时看的事：
  1. 判成了什么（code + 依据）
  2. 有没有「拒绝判定」的出口（现在没有，所以必然落进 P6/P7）
  3. 判型稳定性（阈值扰动 ±20% 后是否改变）

设计原则：
  - 不修改 measure.py，只调用。测试台本身不许改变被测对象。
  - 每类输入都要记录「应该判成什么」，人的判断与机器判断分开存，
    这样差异才是可讨论的，而不是拿机器结果当答案。
"""
import os
import sys
import io
import re
import json
import glob
import random
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure as M

HERE = os.path.dirname(os.path.abspath(__file__))
TSET = os.path.join(HERE, '..', 'testset')
RAW = os.path.join(TSET, 'raw')
OUT = os.path.join(TSET, 'report')

HAN = M.HAN

# ---------------------------------------------------------------- 人工预期
# 「应判」是本人在收集样例时的判断，不是程序得出的。
# 留空表示「说不清该归哪类」——这类正是需要开新原型的候选。
EXPECT = {
    '教材_语文七年级上册': ('教材', '语文'),
    '教材_数学': ('教材', '数学'),
    '教材_物理高中': ('教材', '物理'),
    '教材_化学高中': ('教材', '化学'),
    '工具书_汉字字典': ('工具书', '字典'),
    '法规_宪法': ('法规', '根本法'),
    '法规_刑法': ('法规', '实体法'),
    '法规_行政处罚法': ('法规', '程序法'),
    '年鉴_统计公报2023': ('年鉴', '统计表格'),
    '外文_傲慢与偏见': ('外文', '英文小说'),
}

# 类型 → 该类型内部的细分轴（用户要求：不只测"教材"一个标签）
SUBAXIS = {
    '教材': ['科目（语文/数学/物理/化学/生物/英语）',
             '学段（小学/初中/高中/大学）',
             '形态（课本正文/习题集/教师用书/实验册）'],
    '工具书': ['字典（字头+注音+释义）',
               '词典（词条）/ 百科（条目）',
               '手册（按流程组织）/ 索引（只给位置）'],
    '法规': ['根本法（宪法）',
             '实体法（刑法/民法典）',
             '程序法（诉讼法）',
             '行政法规 / 部门规章 / 地方性法规'],
    '年鉴': ['综合年鉴（多表）',
             '专业年鉴（单领域）',
             '统计公报（叙述+表）',
             '数据手册（纯表）'],
    '期刊': ['学术期刊（摘要+关键词+参考文献）',
             '大众杂志（栏目+专题）',
             '报纸（消息/评论/副刊）'],
    '图鉴': ['植物/动物志（图版+形态描述+分布）',
             '器物图录（器物+年代+尺寸）',
             '地图集（图幅+图例）'],
}


def load(p):
    """旧测试台入口。已改为走 wash.load，与生产路径一致。

    踩过的坑：这个函数原来自己 io.open 读原文，与 wash.load 是两条路。
    于是「测试台说这本能判、流水线判成另一类」的情况会静默发生。
    任何读取入口都必须收敛到 wash.load_ex，并携带 algo_punct 标记。
    """
    import wash
    return wash.load_ex(p)


def junk_ratio(t):
    """脏字符占比：模板残留、乱码、非文本符号。教材 TeX 转换常见。"""
    body = re.sub(r'\s+', '', t)
    if not body:
        return 1.0
    bad = len(re.findall(r'[\\{}<>|~^`_]|\./images/|\\\(|\\\)', body))
    return round(bad / max(1, len(body)), 4)


def table_ratio(t):
    """表格行占比：含 2 个以上竖线/多列对齐的行 / 总行数。
    年鉴、数据手册、教辅答案的典型特征，现有六轴测不到。"""
    lines = [x for x in t.split('\n') if x.strip()]
    if not lines:
        return 0.0
    tbl = sum(1 for x in lines if x.count('|') >= 2
              or len(re.findall(r'\S\s{2,}\S', x)) >= 2)
    return round(tbl / len(lines), 4)


def image_ratio(t):
    """图版标记数：图注、图号、图版编号。图鉴的关键特征。"""
    n = len(re.findall(r'图\s*\d+[-–]\d+|图版|插图|见图|如下图|示意图|彩图', t))
    h = len(HAN.findall(t))
    return round(n * 1000.0 / max(1, h), 2), n


def exercise_ratio(t):
    """习题标记密度：教材/教辅的关键特征。"""
    n = len(re.findall(r'练习|习题|作业|思考题|例题|例\s*\d+|复习题|解答|求|证明|计算|已知', t))
    h = len(HAN.findall(t))
    return round(n * 1000.0 / max(1, h), 2), n


def heading_pattern(t):
    """章节层级：教材/法规/年鉴靠编号组织，与小说靠空行不同。"""
    pats = {
        '第X章/节/单元': len(re.findall(r'第[一二三四五六七八九十百零〇0-9]{1,4}[章节单元课讲]', t)),
        '数字编号(1.2.3)': len(re.findall(r'^\s*\d+(\.\d+){1,3}\s+\S', t, re.M)),
        '第X条': len(re.findall(r'第[一二三四五六七八九十百零〇0-9]{1,4}条', t)),
        '一、二、三': len(re.findall(r'^\s*[一二三四五六七八九十]{1,3}、', t, re.M)),
        '（一）（二）': len(re.findall(r'（[一二三四五六七八九十]{1,3}）', t)),
    }
    return {k: v for k, v in pats.items() if v}


def measure_type(p):
    """在 measure() 之外补充「类型轴」，用于说明现有六轴缺什么。"""
    t, algo = load(p)
    m = M.measure(t, algo_punct=algo)
    # judge 返回三元组：(原型码|None, 依据, kind)
    #   kind='ok'     正常判出
    #   kind='data'   文本不可用（太短/非中文/丢标点）→ 补数据重试
    #   kind='unknown' 数据可用但十类全不成立 → 疑似新类型
    code, ev, kind = M.judge(m)
    r = M.analyze(t, algo_punct=algo)
    img, img_n = image_ratio(t)
    ex, ex_n = exercise_ratio(t)
    return {
        '文件': os.path.basename(p)[:-4],
        '汉字': m['h'],
        '段落数': len([x for x in re.split(r'\n{2,}', t) if HAN.findall(x)]),
        '判型': code,
        '原型': M.ARCH[code][0] if code else None,
        '拒判性质': None if code else kind,
        '置信': r['conf'],
        '稳定性': r['stability'],
        '依据': ev[0] if ev else '',
        '六轴': {k: m[k] for k in ('Q', 'p1', 'p3', 'R', 'D', 'A', 'wen', 'savg', 'smed')},
        '版式': {k: m[k] for k in ('lmed', 'short', 'nline', 'han_ratio', 'han_ratio_raw')},
        '分块': {'吻合': r['fit'], '投票': r['votes'], '混入': r['mixed']},
        '合计格': None,   # 由 main() 统一填：这份样例够不够格参与「类型覆盖」判定
        '补轴': {
            '脏字符率': junk_ratio(t),
            '表格行率': table_ratio(t),
            '图版密度': img,
            '图版标记数': img_n,
            '习题密度': ex,
            '习题标记数': ex_n,
            '章节编号': heading_pattern(t),
        },
        '预期': EXPECT.get(os.path.basename(p)[:-4]),
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(RAW, '*.txt')))
    if not files:
        print(f'测试集为空：{RAW}')
        return

    rows = []
    for p in files:
        r = measure_type(p)
        rows.append(r)

    # 按汉字数降序，长的先看
    rows.sort(key=lambda x: -x['汉字'])

    # 先判定「这份样例有没有参测资格」。这一步必须在解读结果之前做，
    # 否则会把「素材不合格」误读成「遇到新类型」—— 上一版报告的 7 个「判错」里
    # 有 8 个样例本身就是不合格素材（物理教材句均长 1784 字、字典/数学/年鉴
    # 汉字不足 8000），拿它们论证「九类不够」是站不住的。
    for r in rows:
        v = r['版式']
        if r['汉字'] < 8000:
            r['合计格'] = '不合格·太短(%d字)' % r['汉字']
        elif v['han_ratio'] < 60:
            r['合计格'] = '不合格·非中文'
        elif v['lmed'] <= 8:
            r['合计格'] = '不合格·词条版式'
        elif r['六轴']['savg'] > 150:
            # 句读缺失必须算「不合格素材」，不能算「合格但判不出」。
            # 物理教材 1784 字/句、教辅 671 字/句，是 PDF/LaTeX 抽丢句末标点的产物，
            # 任何依赖句长的判据在它上面都无意义 —— 它不构成本系统对教材的能力证据。
            r['合计格'] = '不合格·句读缺失(%.0f字/句)' % r['六轴']['savg']
        else:
            r['合计格'] = '合格'
    qual = [r for r in rows if r['合计格'] == '合格']

    print('%-24s %7s %4s %-10s %-4s %6s %6s %6s %s' % (
        '样例', '汉字', '段', '判型', '置信', '稳定', '吻合', '行中位', '参测资格'))
    print('-' * 112)
    for r in rows:
        if r['原型']:
            tag = r['原型']
        elif r['拒判性质'] == 'data':
            tag = '拒判·数据'
        else:
            tag = '拒判·未知'
        st = r['稳定性'] * 100 if r['稳定性'] is not None else 0.0
        fit = r['分块']['吻合'] if r['分块']['吻合'] is not None else 0
        print('%-24s %7d %4d %-10s %-4s %5.0f%% %5s%% %6d %s' % (
            r['文件'][:22], r['汉字'], r['段落数'], tag, r['置信'],
            st, fit, r['版式']['lmed'], r['合计格']))

    print('\n合格样例 %d / %d。只有合格样例的判型结果才能用来回答「九类够不够」。'
          % (len(qual), len(rows)))
    print('  合格：%s' % ('、'.join(r['文件'] for r in qual) or '（无）'))
    print('  不合格：%s' % ('、'.join('%s(%s)' % (r['文件'], r['合计格'].split('·')[-1])
                                    for r in rows if r['合计格'] != '合格') or '（无）'))

    with io.open(os.path.join(OUT, 'typetest.json'), 'w', encoding='utf-8') as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=1)
    print(f'\n明细 {OUT}/typetest.json')


if __name__ == '__main__':
    main()
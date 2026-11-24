# -*- coding: utf-8 -*-
"""中图分类（CLC）建议：**纯展示**分类，不参与抽取，判错不影响任何产物。

为什么要单独一层：
  - P1–P11 是「因果型」分类 —— 判成 P11 才会去抽物种条目，判错产物全错；
  - CLC 是「描述型」分类 —— 把一本书从 I 文学改成 K 历史，书里的字一个不动。
所以它不需要置信度门槛、不需要拒判，错了改个章就行。

但它必须**落到数据里**，不能页面上现算（见 MEMORY：字段要能在数据里找到原值）。
这里把建议写进 out/<code>/book.json 的 "CLC"，人工改过（来源=人工）的不覆盖。

用法：
    python3 platform/engine/clc.py B56        # 单本，打印建议
    python3 platform/engine/clc.py --all      # 全库回填（幂等）
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

OUT = P.OUT
# 人工改判要跨「重跑」存活：pipeline 会整本重写 book.json，
# 所以人工值另存一份，重跑后由 annotate() 盖回去。
OVERRIDES = os.path.join(P.PLATFORM, 'config', 'clc_overrides.json')

# 中图分类主类。顺序即并列时的优先级。
RULES = [
    ('A', '马克思主义、列宁主义、毛泽东思想', ['马克思', '恩格斯', '列宁', '毛泽东', '邓小平', '资本论']),
    ('B', '哲学、宗教', ['哲学', '伦理', '道德', '宗教', '佛教', '道教', '儒家', '思想史', '心理学', '逻辑']),
    ('C', '社会科学总论', ['社会学', '社会科学', '人口', '统计学', '民族', '社会调查']),
    ('D', '政治、法律', ['政治', '法律', '法学', '宪法', '行政', '党建', '治理',
                     '廉洁', '廉政', '纪律', '监察', '巡视']),
    ('E', '军事', ['军事', '战争', '兵法', '战略', '国防', '武器', '战役']),
    ('F', '经济', ['经济', '金融', '管理', '商业', '营销', '企业', '会计', '贸易', '投资']),
    ('G', '文化、科学、教育、体育', ['教育', '文化', '体育', '新闻', '出版', '图书馆', '传播', '传媒']),
    ('H', '语言、文字', ['语言', '文字', '语法', '词典', '汉语', '英语', '训诂', '音韵']),
    ('I', '文学', ['小说', '诗', '散文', '戏剧', '童话', '寓言', '文学', '曲', '词', '赋',
                   '故事', '传奇', '笔记小说', '神话']),
    ('J', '艺术', ['艺术', '音乐', '绘画', '书法', '戏曲', '电影', '摄影', '设计', '篆刻', '舞蹈']),
    ('K', '历史、地理', ['历史', '地理', '传记', '史', '考古', '文物', '方志', '游记',
                     '回忆录', '院士', '科学家', '人物', '年谱', '生平']),
    ('N', '自然科学总论', ['自然科学', '科学史', '科普', '科学方法']),
    ('O', '数理科学和化学', ['数学', '物理', '化学', '几何', '代数', '力学']),
    ('P', '天文学、地球科学', ['天文', '地质', '气候', '气象', '地图', '海洋', '地震']),
    ('Q', '生物科学', ['植物', '动物', '生物', '物种', '昆虫', '鸟类', '鱼类', '生态', '药用植物', '菌']),
    ('R', '医药、卫生', ['医学', '中医', '药理', '临床', '护理', '养生', '疾病', '本草', '方剂']),
    ('S', '农业科学', ['农业', '农学', '种植', '园艺', '林业', '畜牧', '水产', '土壤']),
    ('T', '工业技术', ['工程', '技术', '计算机', '机械', '电子', '建筑', '化工', '能源', '材料']),
    ('U', '交通运输', ['交通', '铁路', '公路', '航运', '汽车', '船舶']),
    ('V', '航空、航天', ['航空', '航天', '飞机', '火箭', '宇航']),
    ('X', '环境科学、安全科学', ['环境', '污染', '安全', '生态保护', '垃圾']),
    ('Z', '综合性图书', ['百科', '丛书', '文集', '年鉴', '辞典', '大全']),
]

# 原型兜底：标题和标签都没命中时，按书的类型给一个合理的默认类。
PROTO_DEFAULT = {
    'P1': ('D', '规范型多用于法规、标准、制度文件'),
    'P2': ('B', '知识型多为概念、原理这类系统论述'),
    'P3': ('B', '论说型多在思想、伦理、学术论证'),
    'P4': ('I', '叙事型以小说、故事为主'),
    'P5': ('I', '戏曲型归文学（剧本）'),
    'P6': ('I', '散文型归文学'),
    'P7': ('I', '韵文集归文学'),
    'P8': ('Z', '条目型多为工具书、辞书'),
    'P9': ('I', '选集笺注多为文学作品'),
    'P10': ('K', '笔记志书多在史地'),
    'P11': ('Q', '图鉴型多为动植物、器物图谱'),
}

NAME = {c: n for c, n, _ in RULES}
ORDER = [c for c, _, _ in RULES]


def _tag_words(code):
    """从标签库取内容层词，作为补充信号。取不到就算了。"""
    path = os.path.join(P.LIB, 'tags.json')
    try:
        with io.open(path, encoding='utf-8') as fp:
            data = json.load(fp)
    except Exception:
        return []
    for b in data.get('书') or []:
        if b.get('码') != code:
            continue
        # 引用书目、篇名、人物 这几类标签说的是「书里提到谁/引了谁」，
        # 不代表书本身属于哪一类 —— 用它们会把《小王子》判成军事（因为引了《战争飞行员》）。
        # 论断篇 的标签是「论断篇：<篇名>」，本质还是篇名，会带出学科词
        SKIP = ('引用书目', '篇名', '人物', '论断篇')
        words = []
        for lv in ('L4', 'L6', 'L7'):
            for it in (b.get(lv) or []):
                t = it.get('标签') or ''
                if t and (it.get('类') or '') not in SKIP:
                    words.append(t)
        return words
    return []


def suggest(title, proto='', tags=None, author=''):
    """返回 {'代码','名称','依据','来源','置信'}；识别不了时 代码=''。"""
    tags = tags or []
    title = title or ''
    scores, why = {}, {}
    for code, name, kws in RULES:
        hit = []
        for kw in kws:
            # 单字只在标签里用，标题里太容易误命中（诗/史/词/曲）
            if len(kw) >= 2 and kw in title:
                scores[code] = scores.get(code, 0) + 5
                hit.append('标题含「%s」' % kw)
        for kw in kws:
            if any(kw in t for t in tags):
                scores[code] = scores.get(code, 0) + 2
                hit.append('标签含「%s」' % kw)
                break
        if hit:
            why[code] = hit[:3]
    if not scores:
        d = PROTO_DEFAULT.get(proto)
        if d:
            return {'代码': d[0], '名称': NAME[d[0]], '依据': [d[1]],
                    '来源': '规则建议', '置信': '低'}
        return {'代码': '', '名称': '', '依据': ['标题与标签都没有可识别的类目'],
                '来源': '未识别', '置信': ''}
    # 同分时取 RULES 里靠前的类，保证同一本书每次结果稳定
    top = max(scores.values())
    best = next(c for c in ORDER if scores.get(c) == top)
    s = scores[best]
    conf = '高' if s >= 4 else ('中' if s >= 2 else '低')
    return {'代码': best, '名称': NAME[best], '依据': why.get(best, []),
            '来源': '规则建议', '置信': conf}


def load_overrides():
    try:
        with io.open(OVERRIDES, encoding='utf-8') as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_manual(code, clc_code):
    """人工指定，写进 overrides；book.json 那边由 annotate 负责同步。"""
    cc = str(clc_code or '').strip().upper()
    name = NAME.get(cc, '')
    if not cc or not name:
        return None
    data = load_overrides()
    data[code] = {'代码': cc, '名称': name, '依据': ['人工指定'],
                  '来源': '人工', '置信': ''}
    os.makedirs(os.path.dirname(OVERRIDES), exist_ok=True)
    tmp = OVERRIDES + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, OVERRIDES)
    return data[code]


def _read(path):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return None


def _write(path, data):
    tmp = path + '.tmp-clc'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def annotate(code, force=False):
    """给一本书写 CLC。人工标注过的（来源=人工）不动。返回建议 dict。"""
    path = os.path.join(OUT, code, 'book.json')
    b = _read(path)
    if not b:
        return None
    # 版权页 CIP 的分类号是权威数据，压在规则建议之上（人工值仍最高）
    old0 = b.get('CLC') or {}
    if old0.get('来源') == '版权页' and not force:
        return old0
    manual = load_overrides().get(code)
    if manual and not force:
        # 重跑后 book.json 是新的，把人工值盖回去
        if b.get('CLC') != manual:
            b['CLC'] = manual
            _write(path, b)
        return manual
    old = b.get('CLC') or {}
    if old.get('来源') == '人工' and not force:
        return old
    sug = suggest(b.get('book') or '', b.get('原型') or '', _tag_words(code))
    if old.get('代码') == sug.get('代码') and old.get('依据') == sug.get('依据'):
        return old            # 没变就不写盘，避免无谓的 mtime 变动
    b['CLC'] = sug
    _write(path, b)
    return sug


def apply_all(codes=None):
    codes = codes or sorted(d for d in os.listdir(OUT)
                            if os.path.isfile(os.path.join(OUT, d, 'book.json')))
    out = []
    for c in codes:
        r = annotate(c)
        if r is not None:
            out.append((c, r))
    return out


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] == '--all':
        rows = apply_all()
    else:
        rows = [(c, annotate(c)) for c in args]
    for c, r in rows:
        print('%s  %s %s  [%s] %s' % (c, r.get('代码') or '—', r.get('名称') or '未识别',
                                      r.get('置信') or '-', '；'.join(r.get('依据') or [])))
    print('共 %d 本' % len(rows))

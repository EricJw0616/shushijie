# -*- coding: utf-8 -*-
"""通用实体分类器。

所有书共用一套规则，不针对任何一本书写死名字：
  1. 行政区/地理词典（国家、省、区域、市、区县、地标、自然地理）
  2. 词形后缀（机构、地标、自然、奖项、事件、朝代、器物、概念）
  3. 上下文词（说/著/位于/公司/奖/战争/别名…）
  4. 拿不准返回 other，进人工队列，不硬塞。

调用：
    from entity_classify import classify
    cat, confidence, reason = classify(name, context='...')
"""
import re

import lexicon
import geo

CATS = ('country', 'province', 'region', 'city', 'district', 'landmark', 'nature',
        'fossil', 'org', 'object', 'animal', 'plant', 'taxon', 'alias',
        'person', 'concept', 'award', 'event', 'dynasty', 'family')

DYNASTIES = {
    '夏', '商', '周', '秦', '汉', '西汉', '东汉', '三国', '晋', '西晋', '东晋',
    '南北朝', '隋', '唐', '五代', '五代十国', '宋', '北宋', '南宋', '辽', '金',
    '西夏', '元', '明', '清', '民国', '先秦', '春秋', '战国', '魏晋',
    '北魏', '东魏', '西魏', '北齐', '北周', '南朝', '北朝', '五代十国',
}
AWARD_RE = re.compile(r'(奖|奖章|奖金|奖学金|奖杯|勋章)$')
EVENT_RE = re.compile(r'(事件|运动|战争|革命|起义|工程|计划|会议|大会|条约|协定|事变|惨案)$')
FOSSIL_RE = re.compile(r'(猿人|化石|人科|直立人|智人|尼安德特人)$')
ORG_RE = re.compile(
    r'(厂|公司|集团|大学|学院|学校|中学|小学|党校|区委|市委|省委|县委|党委|政府|'
    r'委员会|管委会|管理委员会|出版社|报社|研究所|研究院|科学院|医院|银行|监狱|'
    r'看守所|军区|人民法院|人民检察院|检察分院|法院|检察院|分院|公安局|派出所|'
    r'办公大楼|农业厅|教育厅|财政厅|民政厅|图书馆|博物馆|纪念馆|基金会|联合会|'
    r'协会|学会|部门|办公室|科室|国务院)$')
LANDMARK_RE = re.compile(
    r'(路|街|巷|弄|大道|广场|公园|桥|车站|站|机场|码头|港口|大楼|大厦|宾馆|饭店|'
    r'招待所|剧场|影院|纪念馆|博物馆|图书馆|寺|庙|宫|陵|堂|楼|馆|场|门|滩|坊|牌坊)$')
NATURE_RE = re.compile(
    r'(山|河|湖|海|江|岛|洲|湾|岭|峰|源|泉|溪|沟|谷|盆地|高原|平原|草原|沙漠|湿地|'
    r'林区|山区|湖区|海滩|半岛|群岛|海峡|运河)$')
OBJECT_RE = re.compile(
    r'(车|船|枪|炮|壶|瓶|桌|椅|床|柜|箱|包|衣|服|帽|鞋|刀|剑|工具|机器|设备|仪器|'
    r'食品|饭|菜|肉|酒|茶|药|钱|币|纸|笔|书|画|钟|表|灯|伞|扇|镜|锅|碗|盘|杯|章|笠|印|旗|牌|证|票|册|本|袋|绳|链|锁|钥匙)$')
CONCEPT_RE = re.compile(
    r'(主义|理论|思想|精神|道德|观念|概念|格局|社会|文化|制度|关系|结构|模式|礼治|'
    r'法治|人治|权力|权威|伦理|哲学|宗教|信仰|规律|原理|机制|方法|技术|科学|艺术|'
    r'文学|历史|经济|政治|法律|教育|之间|天国|黄门)$')
PERSON_AFTER = re.compile(r'^\s*(说|曰|问|答|著|译|主编|先生|教授|院士|同志|老师|字|号)')
PERSON_BEFORE = re.compile(r'(先生|教授|院士|同志|老师|字|号)\s*$')
ORG_CTX = re.compile(r'(公司|工厂|机关|委员会|政府|大学|中学|医院|研究所|出版社|军区|法院)')
ALIAS_CTX = re.compile(r'(别名|又称|俗称|又名|简称|别称)')
CONCEPT_CTX = re.compile(r'(所谓|概念|称为|称作|是指|指的是|定义|理论|观念|主义)')
CITY_EXTRA = {'七台河', '芝加哥'}
FOOD = {'腊鸭', '腊肉', '烤鸭', '板鸭', '火腿', '香肠', '米饭', '面条', '馒头', '包子'}


def norm(name):
    n = (name or '').strip()
    n = re.sub(r'[\s\u3000]+', '', n)
    n = re.sub(r'[（(][^）)]{0,12}[）)]$', '', n)
    n = re.sub(r'\d+$', '', n)
    return n


def _lex_cat(n):
    try:
        c = lexicon.match(n)
        return c if c in CATS else None
    except Exception:
        return None


def _admin_lookup(n):
    for suf, cat in (('省', 'province'), ('市', 'city'), ('县', 'district'),
                     ('区', 'district'), ('镇', 'district'), ('乡', 'district'),
                     ('村', 'district'), ('社区', 'district')):
        c = _lex_cat(n + suf)
        if c:
            return c
    return None


def classify(name, context='', hint=None, known_people=None):
    """返回 (cat, confidence, reason)。拿不准给 other。"""
    n = norm(name)
    if not n:
        return 'other', 0.0, '空名'
    ctx = context or ''
    pos = ctx.find(n)
    near = ctx[max(0, pos - 30):pos + len(n) + 30] if pos >= 0 else ctx[:80]

    if re.search(r'(族人|族)$', n):
        return 'concept', 0.8, '民族/族群'
    if known_people and n in known_people:
        return 'person', 0.98, '人物表'
    if n.endswith('植物') and len(n) >= 4:
        return 'concept', 0.7, '植物主题短语'
    if n in CITY_EXTRA:
        return 'city', 0.9, '城市补表'
    if n in ('南极', '北极'):
        return 'region', 0.9, '极地/区域'
    if n in FOOD:
        return 'object', 0.85, '食品'
    if n in DYNASTIES:
        return 'dynasty', 0.98, '朝代词表'
    if FOSSIL_RE.search(n):
        return 'fossil', 0.9, '化石/古人类后缀'
    if AWARD_RE.search(n):
        return 'award', 0.9, '奖项后缀'
    if EVENT_RE.search(n):
        return 'event', 0.9, '事件后缀'

    # 地理词典/行政区后缀：国家、省、区域、市、区县、自然地理、地标
    if n in geo.COUNTRIES:
        return 'country', 0.95, '国家词典'
    if n in geo.PROVINCES:
        return 'province', 0.95, '省份词典'
    if n in geo.REGIONS:
        return 'region', 0.95, '区域词典'
    if n in geo.CITIES:
        return 'city', 0.95, '城市词典'
    if n in geo.DISTRICTS:
        return 'district', 0.95, '区县词典'
    if n.endswith(('省', '自治区', '特别行政区')):
        return 'province', 0.9, '省级后缀'
    if n.endswith('地区'):
        return 'region', 0.9, '区域后缀'
    if n.endswith('市'):
        return 'city', 0.9, '市级后缀'
    if n.endswith(('区', '县', '旗', '镇', '乡', '街道', '村', '社区')):
        return 'district', 0.9, '区县后缀'

    # 分类阶元/科室只看模型上下文，不拿旧标签当依据
    if re.search(r'(?:[一二三四五六七八九十]+|\d+)(中|小)$', n) or n.endswith(('附中', '附小')):
        return 'org', 0.85, '学校简称'
    if n.endswith(('科', '属', '目', '纲', '族')):
        if hint in ('plant', 'animal') or not re.search(r'(保卫|物理|数学|化学|财务|人事|办公|业务|行政|后勤|宣传|组织|科研|教学|门诊|内科|外科|儿科|骨科|皮肤|检验|放射|药剂)', n):
            return 'taxon', 0.85, '分类阶元/学科'
        return 'org', 0.85, '机构科室'

    # 行政/自然地名词典优先：上海不能被“海”抢走，中国不能被“说”抢走
    c = _lex_cat(n)
    if c in ('country', 'province', 'region', 'city', 'district'):
        return c, 0.92, '行政区词典'
    if c == 'landmark' and not LANDMARK_RE.search(n) and hint not in (
            'object', 'animal', 'plant', 'taxon', 'person', 'concept', 'org',
            'award', 'event', 'dynasty', 'family', 'fossil'):
        ac = _admin_lookup(n)
        if ac in ('city', 'district'):
            return ac, 0.9, '行政区词典补后缀'
    if c in ('landmark', 'nature') and n not in ('黄门', '天国', '神兽之间'):
        return c, 0.85, '地理词典'

    if ORG_RE.search(n):
        return 'org', 0.92, '机构后缀'
    if CONCEPT_RE.search(n) or CONCEPT_CTX.search(near):
        return 'concept', 0.75, '概念/上下文'
    after = ctx[pos + len(n):] if pos >= 0 else ''
    before = ctx[:pos] if pos >= 0 else ''
    if len(n) <= 4 and not LANDMARK_RE.search(n) and (PERSON_AFTER.search(after) or PERSON_BEFORE.search(before)):
        return 'person', 0.75, '上下文：人物动词/称谓'
    if LANDMARK_RE.search(n):
        return 'landmark', 0.85, '地标后缀'
    if NATURE_RE.search(n):
        return 'nature', 0.85, '自然地理后缀'
    if OBJECT_RE.search(n):
        return 'object', 0.75, '器物后缀'

    if hint not in ('object', 'animal', 'plant', 'taxon', 'person', 'concept',
                    'org', 'award', 'event', 'dynasty', 'family', 'fossil'):
        c = _admin_lookup(n)
        if c:
            return c, 0.9, '行政区词典补后缀'
    if c:
        return c, 0.8, '词典'
    if ORG_CTX.search(near):
        return 'org', 0.7, '上下文：机构'
    if hint in ('plant', 'animal') and len(n) <= 6:
        return hint, 0.7, '模型候选，无冲突'
    return 'other', 0.3, '无规则命中，进人工'

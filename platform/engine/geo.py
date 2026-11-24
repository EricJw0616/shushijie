# -*- coding: utf-8 -*-
"""地理实体细分：国家 / 省份 / 城市 / 区县 / 道路地标 / 自然地理。

“地名”不再是一个桶；每个地理名必须落到这六级之一。
规则优先，认不出的按来源兜底（行政区数据默认区县，正文默认道路/地标），
宁可粗一级，也不把工厂/机关塞进地理。
"""
import re

GEO_CATS = [
    ('country', '国家'),
    ('province', '省份'),
    ('region', '区域/大区'),
    ('city', '城市'),
    ('district', '区县'),
    ('landmark', '道路/地标'),
    ('nature', '自然地理'),
]
GEO_KEYS = {k for k, _ in GEO_CATS}

COUNTRIES = set('''
中国 中华人民共和国 美国 日本 英国 法国 德国 苏联 俄罗斯 加拿大 澳大利亚 印度
印度尼西亚 韩国 朝鲜 南朝鲜 越南 泰国 新加坡 马来西亚 菲律宾 缅甸 蒙古 意大利
西班牙 葡萄牙 荷兰 比利时 瑞士 瑞典 挪威 丹麦 芬兰 波兰 匈牙利 捷克 希腊 土耳其
埃及 南非 巴西 阿根廷 墨西哥 智利 秘鲁 新西兰 爱尔兰 奥地利 以色列 伊朗 伊拉克
沙特阿拉伯 阿联酋 巴基斯坦 孟加拉国 斯里兰卡 尼泊尔 哈萨克斯坦 乌克兰 白俄罗斯
罗马尼亚 保加利亚 塞尔维亚 克罗地亚 斯洛文尼亚 斯洛伐克 立陶宛 拉脱维亚 爱沙尼亚
冰岛 卢森堡 摩纳哥 梵蒂冈 古巴 委内瑞拉 哥伦比亚 厄瓜多尔 玻利维亚 乌拉圭 巴拉圭
哥斯达黎加 巴拿马 危地马拉 洪都拉斯 萨尔瓦多 尼加拉瓜 多米尼加 海地 牙买加
突尼斯 摩洛哥 阿尔及利亚 利比亚 苏丹 埃塞俄比亚 肯尼亚 坦桑尼亚 尼日利亚 加纳
科特迪瓦 塞内加尔 喀麦隆 刚果 安哥拉 赞比亚 津巴布韦 莫桑比克 马达加斯加 索马里
卢旺达 乌干达 阿富汗 叙利亚 黎巴嫩 约旦 科威特 卡塔尔 巴林 阿曼 也门 格鲁吉亚
亚美尼亚 阿塞拜疆 乌兹别克斯坦 土库曼斯坦 吉尔吉斯斯坦 塔吉克斯坦 巴勒斯坦
文莱 柬埔寨 老挝 马尔代夫 不丹 斐济 巴布亚新几内亚 西德 东德
'''.split())

PROVINCES = set('''
河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南
广东 海南 四川 贵州 云南 陕西 甘肃 青海 台湾 内蒙古 广西 西藏 宁夏 新疆
直隶 湖广 两浙
'''.split())

REGIONS = set('''
东北 东北地区 西北 西北地区 华北 华北地区 华东 华东地区 华南 华南地区
华中 华中地区 西南 西南地区 江南 岭南 关中 京畿 畿辅 中原 塞北 西域
江淮 两淮 燕赵 关东 关内 关外 北大荒 欧洲 亚洲 非洲 美洲 大洋洲
'''.split())

CITIES = set('''
上海 北京 天津 重庆 南京 苏州 无锡 常州 镇江 扬州 南通 徐州 连云港 杭州
宁波 温州 嘉兴 湖州 绍兴 金华 台州 合肥 福州 厦门 泉州 南昌 济南 青岛
烟台 潍坊 淄博 郑州 洛阳 开封 武汉 宜昌 襄阳 长沙 株洲 湘潭 广州 深圳
珠海 佛山 东莞 中山 惠州 汕头 南宁 桂林 海口 三亚 成都 绵阳 贵阳 昆明
西安 宝鸡 咸阳 兰州 西宁 银川 乌鲁木齐 拉萨 呼和浩特 包头 沈阳 大连 鞍山
长春 哈尔滨 大庆 齐齐哈尔 唐山 保定 邯郸 石家庄 秦皇岛 张家口 承德 沧州
廊坊 衡水 邢台 昆山 江阴 常熟 张家港 太仓 吴江 宜兴 溧阳 丹阳 扬中 句容
香港 澳门 喀什 巴黎 芝加哥 七台河 延安 奉化 大丰 吴淞 吴泾 江苏镇江 河北邢台
'''.split())

DISTRICTS = set('''
黄浦 徐汇 长宁 静安 普陀 虹口 杨浦 闵行 宝山 嘉定 浦东 金山 松江 青浦
奉贤 崇明 南市 卢湾 南汇 川沙 闸北 虹桥 安亭 马桥 罗店 赵巷 白鹤 金泽
大场 六合 朱家角 五角场 曹杨 真如 甘泉 宜川 长风
'''.split())

LANDMARK_TAIL = re.compile(
    r'(路|街|巷|弄|大道|广场|公园|桥|车站|站|机场|码头|港口|大楼|大厦|宾馆|饭店|'
    r'招待所|剧场|影院|纪念馆|博物馆|图书馆|寺|庙|宫|陵|堂|楼|馆|场|门|滩|坊|集中营|'
    r'军区|法院|检察院|公安局|派出所|医院|大院|办公大院)$')
NATURE_TAIL = re.compile(
    r'(山|河|湖|海|江|岛|洲|湾|岭|峰|源|泉|溪|沟|谷|盆地|高原|平原|草原|沙漠|湿地|'
    r'林区|山区|湖区|海滩|半岛|群岛|海峡|运河)$')
ORG_HINT = re.compile(
    r'(厂|公司|集团|大学|学院|学校|中学|小学|党校|区委|市委|省委|县委|党委|政府|'
    r'委员会|管委会|出版社|报社|研究所|研究院|科学院|医院|银行|监狱|看守所|军区|'
    r'法院|检察院|公安局|派出所|办公大楼|农业厅|教育厅|财政厅|民政厅)$')
LANDMARK_EXACT = {'外滩', '天安门', '中南海', '怀仁堂', '文化广场', '人民广场',
                  '天安门广场', '中山公园', '西郊公园', '万体馆', '北站', '上海北站',
                  '南京城', '工业展览馆', '徐家汇', '核试验场区'}
ORG_EXACT = {'六院', '市中院', '市高法', '市委大院', '市委书记处办公大院',
             '南京军区', '武汉军区', '沈阳军区'}
GENERIC_GEO = {'广场', '郊区县', '市区', '县城', '首都'}
NATURE_EXACT = {'北大荒', '崇明岛', '东海', '黄浦江', '长江', '黄河', '华山', '衡山'}


def _strip_admin_suffix(n):
    for s in ('维吾尔自治区', '壮族自治区', '回族自治区', '自治区', '特别行政区',
              '自治州', '自治县', '省', '市', '地区', '区', '县', '旗', '镇', '乡', '街道', '村', '社区'):
        if n.endswith(s) and len(n) >= len(s) + 1:
            return n[:-len(s)], s
    return n, ''


def _admin_lookup(n):
    try:
        import lexicon as _lx
        for suf, cat in (('市', 'city'), ('县', 'district'), ('区', 'district'),
                         ('镇', 'district'), ('乡', 'district'), ('村', 'district'),
                         ('省', 'province')):
            if _lx.match(n + suf):
                return cat
        for c in CITIES:
            if n.endswith(c) and n[:-len(c)] in PROVINCES:
                return 'city'
    except Exception:
        pass
    return None


def classify(name, src=''):
    n = (name or '').strip()
    if not n:
        return 'district'
    if n in GENERIC_GEO:
        return 'drop'
    if n in ORG_EXACT:
        return 'org'
    if n in COUNTRIES:
        return 'country'
    if n in REGIONS:
        return 'region'
    if n in PROVINCES:
        return 'province'
    if n in CITIES:
        return 'city'
    if ORG_HINT.search(n):
        return 'org'
    if n in LANDMARK_EXACT:
        return 'landmark'
    if n in NATURE_EXACT:
        return 'nature'
    if n in DISTRICTS:
        return 'district'
    if LANDMARK_TAIL.search(n):
        return 'landmark'
    if NATURE_TAIL.search(n):
        return 'nature'
    if src != 'admin':
        hit = _admin_lookup(n)
        if hit:
            return hit
    base, suf = _strip_admin_suffix(n)
    if suf in ('省', '自治区', '特别行政区'):
        return 'province'
    if suf in ('地区',):
        return 'region'
    if suf in ('市',):
        return 'city'
    if suf in ('区', '县', '旗', '镇', '乡', '街道', '村', '社区'):
        return 'district'
    if suf in ('自治州',):
        return 'city'
    if suf in ('自治县',):
        return 'district'
    if src == 'admin':
        return 'district'
    # 用行政区词典补“短名”：通榆 → 通榆县，富阳 → 富阳区，七台河 → 七台河市
    try:
        import lexicon as _lx
        for suf, cat in (('市', 'city'), ('县', 'district'), ('区', 'district'),
                         ('镇', 'district'), ('乡', 'district'), ('村', 'district'),
                         ('省', 'province')):
            if _lx.match(n + suf):
                return cat
        for c in CITIES:
            if n.endswith(c) and n[:-len(c)] in PROVINCES:
                return 'city'
    except Exception:
        pass
    # 正文里没有后缀的地名：已知城市/区县优先，其余按“道路/地标”兜底
    if base in CITIES:
        return 'city'
    if base in DISTRICTS:
        return 'district'
    if base in REGIONS:
        return 'region'
    if base in PROVINCES:
        return 'province'
    if base in COUNTRIES:
        return 'country'
    return 'landmark'

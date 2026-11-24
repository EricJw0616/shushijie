# -*- coding: utf-8 -*-
"""六轴测量 + 原型判定。

关键修正（此前版本的全部错误都源自这里）：
  汉字正则必须写 \\U00020000（八位），写成 \\u20000 会被解释为
  \\u2000 加字面 0，范围变成「空格～扩展区上限」，把 ASCII 全算进汉字。
"""
import re, os
import paths as P
from collections import Counter as _Counter

HAN = re.compile('[\\u3400-\\u4DBF\\u4E00-\\u9FFF\\uF900-\\uFAFF'
                 '\\U00020000-\\U0002FA1F]')

ARCH = {
    'P1': ('规范型', ['规范型规则卡', '条款索引', '换版差异表']),
    'P2': ('知识型', ['概念卡', '先修图谱', '术语表', '易错点']),
    'P3': ('论说型', ['规则卡+边界', '主题卡', '镜像矛盾']),
    'P4': ('叙事型', ['人物关系图谱', '情节链', '场所索引']),
    'P5': ('戏曲型', ['人物关系图谱', '出目情节链', '曲牌科介索引']),
    'P6': ('散文型', ['引书谱', '意象谱', '态度演变曲线']),
    'P7': ('韵文集型', ['意象谱', '名句索引', '韵律统计']),
    'P8': ('条目型', ['词条结构化', '交叉引用', '属性表']),
    'P9': ('选集笺注型', ['篇目索引', '注疏分层', '异文对照']),
    'P10': ('笔记志书型', ['条目索引', '专名表', '引书谱']),
    'P11': ('图鉴型', ['物种条目卡', '字段表', '科名索引']),
    'P12': ('纪事型', ['人物条目', '篇目索引', '引书谱']),
}
# P10 是 2026-11-07 新增。为什么必须有：34 本真实文本里有 3 本落不进原九类
#   —— 梦溪笔谈（考据笔记）、陶庵梦忆（小品笔记）、东京梦华录（城市志）。
#   它们的共同点不是「没有特征」，而是「特征全落在中间」：
#   有引书但不成论（R/D 都低）、有叙事但无对白（Q<10）、句子短但不押韵。
#   把它们硬塞进 P3 或 P6 是错的，拒判又丢掉了三本真书。
#   这一类真正该抽的产物是「条目索引 + 名物表」，与九类都不同。


def f(pat, body, h):
    return round(len(re.findall(pat, body)) * 1000.0 / max(1, h), 1)


def _lines_pre(text):
    """非空行列表。抽出成函数是必须的：entp 轴同一个列表要取三次，
    若在列表推导里反复 text.split('\n')，100 万字的书写一次要几秒。"""
    return [x.strip() for x in text.split('\n') if x.strip()]


def measure(text, algo_punct=False):
    body = re.sub(r'\s+', '', text)
    h = len(HAN.findall(body))
    sents = [s for s in re.split(r'[。！？；]', body)
             if len(HAN.findall(s)) >= 3]
    lens = [len(HAN.findall(s)) for s in sents] or [1]
    m = {
        'h': h,
        'nsent': len(sents),
        'savg': round(sum(lens) / len(lens), 1),
        'smed': sorted(lens)[len(lens) // 2],
        # 句子等长度：句长落在最常见 2 个取值上的比例。
        # 韵文的核心特征不是「句子短」而是「句子等长」——五言、七言、词牌，
        # 句长集中在两三个值上。技术说明文句子也短（《天工开物》smed=16），
        # 但长短参差（前 2 种长度只占 12%），与诗（唐诗三百首 70%）截然不同。
        'mode2': round(sum(_v for _k, _v in _Counter(lens).most_common(2))
                       * 100.0 / max(1, len(lens))),
        'p3': f('[他她]', body, h),
        'p1': f('[我]', body, h),
        'wen': f('[之乎者也矣焉哉曰]', body, h),
        'R': f('必|不可|不得|须|应当|禁止|严禁|不准|毋|勿|不宜|最忌|切忌|当先|务须', body, h),
        # D 的定义句式不能绑标点。旧写法是 '者，'，要求「者」后紧跟中文逗号 ——
        # 一旦文本被换成白文（Kanripo 底本）或被自动断句（句号），D 恒为 0，
        # P2/P3 的知识型判定全部失效。实测：齐民要术、逸周书、孔子家语、
        # 三辅黄图四本断句后 D 全为 0.0，而它们明显有定义句。
        # 改为「者」后允许任意标点或直接接字，再补上常见的文言定义标记。
        'D': f('所谓|谓之|是指|即是|称为|简称|者[，。、；：]|者$|'
               r'曰[^，。]{0,8}者|之為|之为|名曰|一名', body, h),
        'A': f('是故|是以|因此|所以|然而|何以|故曰|不然|可见|反之|然则|若夫', body, h),
        'G': f('故曰|由此观之|大抵|总之|要之|盖|夫', body, h),
    }
    # ---------- 数据质量轴（判型前的前置门，不算语体） ----------
    # 这三项不参与判型，只用来回答「这份文本能不能拿去测语体」。
    m['nchar'] = len(body)                                   # 非空白字符数
    # 汉字率：分母只算「有文字属性的字符」= 汉字+拉丁字母+假名+谚文。
    # 修正（2026-11-07）：旧口径分母是全部非空白字符，把数字、标点、注音
    # 符号都算进分母。《康熙字典》式工具书每字带拼音与注音符号，
    # 旧口径 52.7% 被误判「非中文文本」；只为数字的统计公报旧口径 45.7%。
    # 新口径只问「在文字里汉字占多少」，字典 75.9%、年鉴 100%。二者均为中文。
    _b = body
    _lat = len(re.findall(r'[A-Za-z]', _b))
    _kana = len(re.findall(r'[\u3040-\u30ff]', _b))
    _hang = len(re.findall(r'[\uac00-\ud7af]', _b))
    m['han_ratio'] = round(h * 100.0 / max(1, h + _lat + _kana + _hang), 1)
    # 旧口径保留为记录字段，供对比，不再参与判定。
    m['han_ratio_raw'] = round(h * 100.0 / max(1, len(body)), 1)
    m['punct'] = round(len(re.findall(r'[。！？]', text)) * 1000.0 / max(1, h), 1)  # 句末标点/千字
    # 算法断句标记必须由调用方**显式传入**，不能靠测量猜。
    #
    # 走过且失败的路（勿再试）：想用测量值识别「这段标点是算出来的」。
    # 把 57 本真人标点文本与 7 本算法断句文本放在一起比：
    #   真人 punct 中位 52 [9~149]、savg 中位 17.4、smed 中位 15
    #   算法 punct 中位 83 [67~433]、savg 中位 12.5、smed 中位 12
    # 三个轴**全部重叠**：真人标点的《易经》punct=84.2 比算法断句的《齐民要术》
    # 83.4 还高；《聊斋》77.9 与算法断句的《握奇经》80.3 无法区分。
    # 原因是文言本身句子就短，算法断句落在同一个分布里。
    # 结论：这是**来源属性**，不是**测量属性**，必须由数据流携带。
    #
    # 因此 measure() 接受 algo_punct 参数；judge 据此收紧韵文判据。
    # 判不了就不许判 —— 宁可对白文古籍拒判并要求用户提供带标点底本，
    # 也不许把散文误判成韵文集（那会让后续所有产物错位）。
    m['algo_punct'] = bool(algo_punct)
    # 逗句比 = 逗号顿号数 / 句末标点数。中文古籍排印有两派：
    # 一派用「。」断句（史记 2.0、红楼梦 5.5），另一派几乎全用「，」并在段末才用「。」。
    # 《左传》电子本（Gutenberg #24136）逗句比 24.2，全库其余 45 本最高 3.4。
    # 这类文本的「句长」统计的是「一个逗号到下一个逗号」，savg 108.4 完全失真，
    # 但它的汉字率、行长都正常，前面的门拦不住。必须单独判。
    _nend = len(re.findall(r'[。！？]', text))
    _ncom = text.count('，') + text.count('、') + text.count('；') + text.count('：')
    m['lo'] = round(_ncom / float(_nend), 1) if _nend else 99.9
    # ---------- 版式轴（当前仅测量、不参与判型；供「待开原型」判定用） ----------
    lines = [x for x in text.split('\n') if x.strip()]
    m['tbl'] = round(sum(1 for x in lines if x.count('|') >= 2)
                     * 100.0 / max(1, len(lines)), 1)         # 表格行率 %
    # 图鉴字段标签密度：行首出现「来 源 / 生 境 / 分 布 / 采 制 …」的次数 / 千汉字。
    # 图鉴的体例不在语体上，而在「每条都带同一组字段标签」。
    # 实测这本 20.5/千；55 本基准书全部 0.0/千（一个字都没有），中间是断档的。
    _alb = re.compile(r'^[\s\u3000]*(?:来\s*源|别\s*名|俗\s*名|原\s*植\s*物|'
                      r'生\s*境|分\s*布|采\s*制|性味功效|性味功能|主治用法|'
                      r'用\s*量|附\s*注|附\s*方)')
    m['alb'] = round(sum(1 for x in lines if _alb.match(x)) * 1000.0 / max(1, h), 1)
    m['ex'] = round(len(re.findall(
        r'练习|习题|作业|思考题|例题|复习题|解答|证明', text)) * 1000.0 / max(1, h), 1)  # 习题密度
    # 术语密度：每千字里「是/即/由于/因此/包含/分为…」这类表意连接词的次数。
    # 用途：把「说明文」和「清单」分开。二者的句长都落在 28~45 之间，
    # 光看句长必然混淆（实测：参数清单 savg=30，教材 savg=33，无法区分）。
    # 但清单没有表意连接词：实测清单 0.0，全部真实文本 ≥6.7，教材 8~28。
    m['term'] = round(len(re.findall(
        r'是|为|即|指|由于|因为|因此|从而|导致|使得|构成|包含|分为|属于|称为',
        text)) * 1000.0 / max(1, h), 1)
    # 顿逗密度：每千字「，」「、」次数。仅作记录，当前不参与判型。
    m['comma'] = round((text.count('，') + text.count('、'))
                       * 1000.0 / max(1, h), 1)
    # 对白占比：引号内汉字 / 总汉字
    quotes = re.findall(r'[“「『]([^”」』]{2,400})[”」』]', body)
    m['Q'] = round(sum(len(HAN.findall(q)) for q in quotes) * 100.0 / max(1, h), 1)
    # 格式轴
    m['chu'] = len(re.findall(r'^第[一二三四五六七八九十百]{1,3}[出折幕]', text, re.M))
    m['hui'] = len(re.findall(r'^第[一二三四五六七八九十百零〇0-9]{1,4}[回]', text, re.M))
    m['tiao'] = len(re.findall(r'^第[一二三四五六七八九十百零〇0-9]{1,4}条', text, re.M))
    m['qupai'] = len(re.findall(r'【[^】]{1,8}】', text))
    m['kejie'] = len(re.findall(r'[\[［][^\]］]{1,12}介[\]］]', text))
    m['tm'] = (len(re.findall(r'又[东南西北]?\s*[一二三四五六七八九十百]{1,3}里', text))
               + sum(text.count(x) for x in ['有兽焉', '有鸟焉', '有木焉', '有草焉'])
               + len(re.findall(r'曰[^\s，。]{1,6}之山', text)))
    m['ping'] = sum(text.count(x) for x in ['【评】', '【注】', '【译】', '【释】', '【解】', '吴评'])
    # ---------- 对白纯度：把「人物说话」与「引书引文」分开 ----------
    # 为什么必须有：Q（引号内汉字占比）把两者当成同一件事，导致三本考据/史料书
    # 被判成 P4 叙事型 —— 日知录 Q=37.3（全是引经据典，《》6700 处）、
    # 盐铁论 Q=69.6（全是「大夫曰／文学曰」的政论对辩）、随园诗话 Q=49.2（引诗）。
    # 判据：引号段前 10 字或后 10 字里有「说/道/问/答/云/曰」等引导词，才算对白。
    # 实测区分度：儒林外史纯度 93%（真小说），日知录 40%、随园诗话 75% 但引书 12.6/千。
    _q = re.findall(r'[“「『]([^”」』]{2,500})[”」』]', body)
    _tq = _dq = 0
    _nq = _nd = 0
    _qlens = []
    for _mm in re.finditer(r'[“「『]([^”」』]{2,500})[”」』]', body):
        _s = _mm.group(1)
        _nh = len(HAN.findall(_s))
        _tq += _nh
        _nq += 1
        if _nh:
            _qlens.append(_nh)
        _pre = body[max(0, _mm.start() - 10):_mm.start()]
        _post = body[_mm.end():_mm.end() + 10]
        if re.search(r'[说道问答喊叫嚷骂笑叹斥答曰云]', _pre) or re.search(r'[说道问答]', _post):
            _dq += _nh
            _nd += 1
    m['Qd'] = round(_dq * 100.0 / max(1, h), 1)                       # 真对白占汉字比
    m['qpur'] = round(_nd * 100.0 / max(1, _nq))                      # 引号段中有引导词的比例 %
    m['qmed'] = sorted(_qlens)[len(_qlens) // 2] if _qlens else 0     # 引号段中位长
    # 引书密度：每千字《》次数。论说/考据与叙事的硬分界之一。
    m['citek'] = round(len(re.findall(r'《[^》]{1,40}》', body)) * 1000.0 / max(1, h), 1)
    # 曰-引语密度：每千字「X曰：」。先秦两汉子书、史料的对辩句式。
    m['yuek'] = round(len(re.findall(r'[^\s，。！？：；]{1,6}曰[：:「“]', body))
                      * 1000.0 / max(1, h), 1)
    # 事件推进词：每千字「遂/乃/于是/既而/俄而」等叙事连接词。
    # 用途：辅助描述叙事强度。**不能单独用来区分语录体与小说** ——
    # 实测《金瓶梅》只有 1.3/千，与《论语》1.2 几乎一样，而《金瓶梅》确是小说。
    # 保留为记录字段，判型时不单独作为分界。
    m['evk'] = round(len(re.findall(r'遂|乃|於是|于是|然后|既而|俄而|顷之|已而|忽',
                                    body)) * 1000.0 / max(1, h), 1)
    # 「曰/问/答」开头的段落占比：区分语录体与叙事体。
    # 语录体的每一则都是一个独立问答（子曰／孟子对曰／文学曰），段首就是说话人；
    # 小说段落是连续描写，段首极少直接是「X曰」。
    # 实测：论语 61%、盐铁论 49%、孟子 35%、国语 14%，
    #       而红楼梦 1%、金瓶梅 4%、三国 9%、史记 7%、聊斋 8%、文心雕龙 9%。
    # 取 20% 为界：语录体全部 >=35%（国语 14% 会被另两条判据接住），
    # 叙事与论说全部 <=9%。
    _ps = [x.strip() for x in text.split('\n') if x.strip()]
    m['yhead'] = round(sum(1 for _p in _ps
                           if re.match(r'^[^，。！？：；]{1,8}(曰|对曰|问|答|云)',
                                       _p)) * 100.0 / max(1, len(_ps)))
    # 「凡…之礼/之事/之法」句式密度（每万字）。
    # 用途：《周礼》《礼记》这类礼制典籍没有「第X条」编号，但通篇是
    # 「凡为人子之礼…」「凡与客入者…」的规范条文，与法规同类，产物也一样
    # （规则卡 + 条目索引）。实测：周礼 7.5/万、礼记 0.8/万，
    # 而 34 本其余文本全部 <=0.2/万（聊斋 0.1、日知录 0.2）。
    m['fan'] = round(len(re.findall(r'凡[^。！？]{2,20}(之禮|之礼|之事|之法|之道)', body))
                     * 10000.0 / max(1, h), 1)
    # 「凡」字词频（每千字）：礼制文本的第二个标志。
    m['fank'] = round(body.count('凡') * 1000.0 / max(1, h), 1)
    # 训释句密度：每千字「也。」次数 —— 词典/训释体的硬标志。
    # 用途：把《尔雅》这类「初，哉，首，基…始也。」的同义词连缀体认出来。
    # 这类书的句长指标全部失真（一行一条词条，smed=4），必须走独立判据。
    # 实测：尔雅 64.5/千，第二名孟子 17.4、第三名天工开物 6.6 —— 断档，不是渐变。
    m['yek'] = round(body.count('也。') * 1000.0 / max(1, h), 1)
    # 四季纪月密度：每千字「，春，」这类四季标记 —— 编年体的硬标志。
    # 用途：《左传》是叙事体，但对白不用引号（Qd=0），四条对白判据全接不住。
    # 只有编年体按「元年，春，王正月」「夏四月」这样逐年逐季记事。
    # 实测：左传 1.3/千；史记 0.0、汉书 0.0、国语 0.0 —— 纪传体不用四季。
    m['season'] = round(len(re.findall(r'[，。][春夏秋冬][，。]', body))
                        * 1000.0 / max(1, h), 2)
    # ---------- 戏曲「脚本标记」密度 ----------
    # 旧判据靠 chu（第X出）+ qupai（【】）+ kejie（[X介]），三个都是「某一体例专用」，
    # 换一个版本就全失效。《西厢记》用 [末云]/[红唱]/[夫人上白]，【】一个都没有，
    # chu=0、kejie 只认「介」不认「科」，于是被判成 P6 散文型。
    # 新判据：统计方括号里的「舞台指示」——角色名或 云/唱/白/科/介/上/下/开/扮。
    m['jb'] = round(sum(1 for _b in re.findall(r'[\[［]([^\]］]{0,14})[\]］]', text)
                        if re.search(r'(云|雲|唱|白|科|介|上|下|開|开|扮|引|見|见)', _b)
                        or re.match(r'^(生|旦|净|淨|末|丑|外|贴|貼|副)', _b.strip()))
                    * 10000.0 / max(1, h), 1)
    # ---------- 条目化程度 ----------
    # 独立成行、<=12 字、无句读的短标题，且下一行是长正文 → 计一个条目。
    # 用途：识别笔记体/志书体（陶庵梦忆 42%、东京梦华录 29%、随园诗话 43%），
    # 这三本旧实现全部拒判或误判成叙事。
    m['entp'] = round(sum(1 for _i, _x in enumerate(_lines_pre(text)[:-1])
                          if 2 <= len(_x) <= 12
                          and not re.search(r'[。！？；，、：]', _x)
                          and HAN.search(_x) and len(_lines_pre(text)[_i + 1]) >= 30)
                      * 100.0 / max(1, len(_lines_pre(text))), 1)
    # 圈号条目（○/●/◎/◇ 开头）：日知录体例，每万汉字个数。
    m['circ'] = round(sum(1 for _x in _lines_pre(text) if re.match(r'^[○●◯◎◇◆]', _x))
                      * 10000.0 / max(1, h), 1)
    # 处所名物密度：每千字「东西南北门桥街巷殿院寺山水州府县」等字次数。
    # 用途：识别地理书/方志/游记（徐霞客 101.9/千、山海经 132.0/千），
    # 这两本旧实现里山海经被判 P8「条目型」是碰对的，理由（里程句式）不对。
    m['plac'] = round(sum(body.count(_c) for _c in
                          '东西南北门桥街巷殿院寺山水的里州府县城乡楼阁堂亭台池湖江河岸')
                      * 1000.0 / max(1, h), 1)
    # 里程句式：旧 tm 轴把「又X里」与「有兽焉」混在一起算。
    # 实测徐霞客 tm=1475 里 1475 条全是「又十里」，一处「有兽焉」都没有。
    # 拆开：mile 属地志/游记，entx 属山海经式名物条目。二者产物完全不同。
    m['mile'] = len(re.findall(r'又[东南西北]?\s*[一二三四五六七八九十百]{1,3}里', text))
    m['entx'] = (sum(text.count(x) for x in ['有兽焉', '有鸟焉', '有木焉', '有草焉'])
                 + len(re.findall(r'曰[^\s，。]{1,6}之山', text)))
    m['tm'] = m['mile'] + m['entx']        # 保留旧字段以兼容，但不再单独当判据
    # 农工词密度：把「技术专著」和「礼制条文」分开的最后一道关键轴。
    # 为什么必须有：两者都用「凡」字枚举（天工开物 11.4/千、周礼 12.3/千、
    # 齐民要术 2.5/千），字面无法区分；D/term 在齐民要术上又双双偏低
    # （D=2.1、term=4.3），所以它一路掉到礼制判据里被判成 P1。
    # 真正稳定的差异是「这本书在谈耕作器物，还是在谈人的行为规范」。
    # 实测（/千）：齐民要术 44.1、天工开物 25.3、茶经 10.6、
    #   建筑卷 8.7、陶庵梦忆 6.6、山海经 6.4、周礼 5.0、礼记 2.2。
    # 20 以上只剩两本真正的农工专著，20 以下无一本误伤。
    _CRAFT = '耕種种苗田土糞粪灌溉鋤锄收穫获蠶蚕織织造煮蒸燒烧磨鍊炼冶陶窯窑'
    m['craft'] = round(sum(body.count(_c) for _c in _CRAFT)
                       * 1000.0 / max(1, h), 1)
    # ---------- 版式轴：文本的自然单位是不是「句」 ----------
    # 为什么要有：句长类指标（savg/smed）默认「句」是文本的最小自然单位。
    # 字词典、韵书、字表、索引的最小单位是「字/词」——一行一个义项、一行一个字头，
    # 句末标点稀少且分布随机，此时 smed 小、Q 低、p3 低会同时成立，
    # 恰好命中 P7 韵文集的全部条件，于是《康熙字典》式文本被判成「韵文集·高置信」。
    # 这是「高置信的错判」，比拒判危险，必须单独拦。
    _lines = [x.strip() for x in text.split('\n') if x.strip()]
    _ls = sorted(len(x) for x in _lines) if _lines else [1]
    m['nline'] = len(_lines)
    m['lmed'] = _ls[len(_ls) // 2]                                  # 行长中位数
    m['short'] = round(sum(1 for x in _lines if 1 <= len(x) <= 12)
                       * 100.0 / max(1, len(_lines)), 1)             # 短行率 %
    return m


# ---------- 合集识别：一本书里明写着几种文体 ----------
# 为什么需要：《你是人间的四月天·文学卷》整本被判 P6 散文型，但它的实测构成是
#   散文 19.6% / 小说 39.9% / 评论 5.7% / 诗歌 5.6% / 剧本 29.2%
# 散文只占两成，小说与剧本合起来近七成。**把它叫「散文集」是错的。**
# 这类书不能靠单一原型概括，必须报出内部构成 —— 这就是「多种文体」的诚实表达方式。
# 判据只用书上自己写的分隔标题，不猜：OCR 后标题常被拆成「散\n \n文」，
# 故先把连续 1~3 字的短行拼起来再匹配。
GENRE = ['散文', '小说', '诗歌', '诗词', '评论', '剧本', '戏剧', '杂文', '随笔',
         '译文', '序跋', '书信', '日记', '游记', '报告文学', '童话', '寓言',
         '文论', '曲艺', '访谈', '演讲']


def sections(text):
    """找书内明示的文体分隔标题，返回 [(文体, 起始行, 汉字数)]。

    只认独占一行（拼合后）的文体名，且该行前后是空行/页标记，
    避免把正文里的「小说」二字当成标题。
    """
    lines = text.split('\n')
    marks = []
    i = 0
    while i < len(lines):
        # 从第 i 行起拼接最多 3 行极短行（不含页标记）
        buf, j, used = '', i, 0
        while j < len(lines) and used < 3:
            s = lines[j].strip()
            if s.startswith('<<<PAGE'):
                break
            if len(s) <= 2 and not re.search(r'[。，、！？；：]', s):
                buf += s
                j += 1
                used += 1
                if buf in GENRE:
                    break
            else:
                break
        if buf in GENRE:
            marks.append((buf, i))
            i = j
        else:
            i += 1
    out = []
    for k, (name, ln) in enumerate(marks):
        end = marks[k + 1][1] if k + 1 < len(marks) else len(lines)
        h = len(HAN.findall('\n'.join(lines[ln:end])))
        if h >= 500:                      # 太短的段（只一个标题）不计
            out.append((name, ln, h))
    return out


# ---------- 判型前的数据质量门 ----------
# 阈值全部由 22 本已知书实测下界倒推，不凭感觉定：
#   22 本最低：汉字 51065、汉字率 74.5%、句均长 32.0
# 这三项检查的是「这份文本能不能拿去测语体」，与「它属于哪一类」无关。
MIN_HAN = 8000        # 真实书都远超（最小《野草》51540）；低于此判型不可靠
MIN_HAN_RATIO = 60.0  # 22 本最低 90.6%（新口径），取 60 留余量。旧口径下界 74.5%
MAX_SAVG = 150.0      # 22 本最高 32.0。句均长爆到几百上千，说明句末标点被丢了
                      # （LaTeX/PDF 抽取的典型症状：物理教材 1784 字/句）。
                      # 注意不能用「句末标点/千字」代替：法条一句一条，
                      # 《刑法》只有 14.6/千字但句均 41.9 字，完全正常。


def gate(m):
    """判型前置门。返回 (硬拒, 不可信特征名单)。

    为什么必须有硬拒：此前的实现把「没测到」当成「测到了且为 0」。
    汉字数为 0 时 smed 退化成 1，于是 smed<=17、Q<5、p3<4、R<10
    四个条件全部因为「没数据」而成立，一本纯英文书被判成中文韵文集。
    这类错误不是判错类，是根本没有判的资格。

    ---- 2026-11-08 重构：把「不可信」与「不可判」分开 ----
    旧实现有两个门会让整本书拒判：
      · 词条排版（尔雅 lmed<=8 且 smed<=8）
      · 逗句比异常（左传 lo=24.2）
    但这两件事的实质是**句长类指标失真**，不是「这本书没有类型」。
    尔雅是好端端的词典（P8 条目型），左传是好端端的编年史（P4 叙事型）。
    把整本书拒掉，等于因为尺子量不准就说东西不存在。

    现在改为：这些门只返回**不可信特征名单**，由 judge 内部逐条回避
    ——凡是用到 smed/savg/mode2/lo 的分支一律跳过，其余分支照常跑。
    硬拒只剩三条真·数据不可用：样本过短、非中文、句读整体缺失。

    注意区分两类拒判（混淆会把结论读反）：
      kind='data'    文本本身不可用（太短、非中文、丢标点）→ 补数据重试
      kind='unknown' 数据可用，但九类主动特征全不成立   → 疑似第十类
    """
    bad = []
    if m['savg'] > MAX_SAVG:
        # 句均长爆到几百上千，句末标点基本被丢了
        return (('句读缺失',
                 f"句均长{m['savg']}字>{MAX_SAVG}，疑为 PDF/LaTeX 抽取丢句末标点，"
                 f"句长类指标不可信，无法判型", 'data'), [])
    if m['h'] < MIN_HAN:
        # 样本过短是**体量**问题，不是类型问题。
        # 2026-11-08 改：不硬拒判，让 judge 照常往下判，置信度末尾按体量封顶为「低」。
        # 理由：茶经 6159 字、诗品 5771 字都是完整传世的真书，
        # 拒判等于让它们连切段和候选卡都拿不到（这正是旧版 4 本書 0 产出的根因）。
        # 不改判据阈值，只如实降低对结论的信任度。
        return (None, ['small'])
    if m['han_ratio'] < MIN_HAN_RATIO:
        return (('非中文文本',
                 f"文字中汉字仅占{m['han_ratio']}%<{MIN_HAN_RATIO}%，"
                 f"疑为非中文（日/韩/英文占多数）", 'data'), [])
    # ---- 以下两项不再拒判，只标记「哪些指标不可信」 ----
    # 词条排版：一行只放一个字头，smed 塌到 4 字。smed/savg/mode2 全失真。
    if m['lmed'] <= 8 and m['smed'] <= 8:
        bad += ['smed', 'savg', 'mode2']
    # 逗句比过高：全篇逗号断句、段末才用句号。savg 统计的是「逗号到逗号」。
    # 实测 46 本里只有《左传》电子本超过 3.4（24.2），同书其他排印本≈2。
    if m['lo'] > 8:
        bad += ['savg', 'lo']
    return None, bad


def judge(m):
    """返回 (原型码, 依据列表, 置信度)。顺序即优先级。

    置信度的定义（v2，2026-11-07 改）：
      旧版是每个分支末尾写死的字符串，衡量的是「这条规则的阈值有多严」。
      新版改为实测：余量 = 该分支各条件相对阈值的达成比的较小值。
        ≥1.0 才成立；1.0 表示刚好压线，2.0 表示两倍余量（已上限封顶）。
      再用「次优原型与本原型的分离度」修正，防止被相邻类挤占。
      三档：余量≥1.5 且分离度≥1.3 → 高；余量≥1.15 → 中；其余 → 低。
    """
    ev = []
    g, bad = gate(m)
    if g:
        return None, [f"拒判·{g[0]}：{g[1]}"], g[2]
    # bad 里的指标不可信（句长类失真）。凡是用到它们的判据一律回避，
    # 其余判据照常跑 —— 这才是「尺子不准就换尺子」，而不是「尺子不准就说没东西」。
    # 实测：尔雅 bad=['smed','savg','mode2']（词典体 lmed=6）；
    #       左传 bad=['savg','lo']（逗句比 24.2）。
    # 旧实现把这两本整本拒判，等于丢了两本真好书。
    ok_len = not ({'savg', 'smed', 'mode2'} & set(bad))

    # ---- P11 图鉴型（字段标签是排印层自带的硬标记，优先于所有语体判据） ----
    # 图鉴的正文不是「篇→段」，而是「页→条目→字段」；语体统计对它全部无意义。
    # 判据只看一条：每千汉字里有多少行首字段标签。
    # 实测图志 20.5/千，55 本基准书 0.0/千 —— 它不需要和别的类抢。
    if m.get('alb', 0) >= 2:
        return 'P11', [f"字段标签{m['alb']}/千（来 源/生 境/分 布/采 制…）"], 'ok'

    # ---- P8 词典/训释体（必须在所有句长判据之前） ----
    # 尔雅 lmed=6、smed=4，句长指标全不可信。它的体例特征不在句长上，
    # 而在「一连串同义词，末字用『也』收」的训释句：X，Y，Z，…也。
    # 实测「也。」密度：尔雅 64.5/千，第二名孟子 17.4/千，第三名天工开物 6.6/千
    # —— 中间是断档的，不是渐变。
    # 这条同时解决了「旧版把尔雅判成 P7 韵文集」的老问题
    # （smed=4、mode2=60 恰好命中「句短且等长」）。
    if m.get('yek', 0) >= 30 and m['Qd'] < 5:
        return 'P8', [f"训释句密度{m['yek']}/千（X，Y，…也。连缀同义词）"], 'ok'
    # ---- P5 戏曲：舞台指示密度 ----
    # 旧判据只认 chu（第X出）与「[X介]」，换个体例就全失效。
    # 《西厢记》用 [末云]/[红唱]/[夫人上白]，一条「介」都没有，chu=0、qupai=0，
    # 于是被判成 P6 散文型。改用「舞台指示密度」jb：
    # 实测牡丹亭 344.9/万、西厢记 260.1/万，第三名（文学卷）0.3/万 —— 中间是空的。
    if m['jb'] >= 8:
        return 'P5', [f"舞台指示{m['jb']}/万（方括号内角色名或云唱白科介）"], 'ok'
    if m['chu'] >= 8 and m['kejie'] >= 20:
        return 'P5', [f"出/折{m['chu']} 科介{m['kejie']}"], 'ok'
    if m['tiao'] >= 20:
        return 'P1', [f"条款编号{m['tiao']}"], 'ok'
    # ---- P2 知识型 · 技术专著（必须先于礼制「凡式」） ----
    # 《天工开物》通篇「凡稻種最多」「凡秧田一畝所生秧……」的凡字枚举，
    # 与《周礼》《礼记》的「凡為人子之禮」在**字面上几乎无法区分**：
    #   凡字频  天工开物 11.4/千、周礼 12.3/千、礼记 1.7/千 —— 天工开物比周礼还高。
    # 试过且失败的判据（勿再试）：
    #   ① 凡句含礼制词比例：天工开物 31%、周礼 56%、论语 0% —— 无语义意义；
    #   ② 全书礼制词密度/千：天工 24.3、周礼 40.8、论语 108.4 —— 完全不分离；
    #   ③ 凡句含强制副词（必/毋/勿/禁）比例：天工 30.3%、周礼 17.3% —— 反而反了。
    # 真正的分离在「定义 + 术语」这一对轴上：工艺书要给器物/工序下定义并用专门词，
    # 礼制书是行为规范，不下定义。
    #   天工开物 D=7.1 term=5.0 Qd=0.1 R=3.8
    #   周礼     D=3.5 term=0.9 Qd=0.4 R=1.1
    #   礼记     D=5.8 term=4.8 Qd=21.8 R=7.3  ← 靠 Qd 挡（礼制有问答、工艺书没有）
    #   孟子     D=7.4 term=7.4 Qd=70.2        ← 靠 Qd 挡
    #   日知录   D=5.9 term=20.2 Qd=18.1       ← 靠 Qd 挡
    # 因此这条判据不能放在 P1 之后（会被凡式抢走），必须前置。
    # 补充（2026-11-07 盲测暴露）：D/term 在**白文**工艺书上会双双偏低。
    # 《齐民要术》（Kanripo 白文）D=2.1、term=4.3，够不上上面这条，
    # 于是掉进下面的礼制判据被判成 P1。可靠的替代轴是农工词密度 craft：
    #   齐民要术 44.1、天工开物 25.3、茶经 10.6 —— 然后断档到 8.7（建筑卷）。
    #   周礼 5.0、礼记 2.2。取 20 为界，只认真正的农工专著。
    # 这一条用「凡字枚举」当必要条件，避免把《建筑卷》这类现代说明文收进来。
    if (m['D'] >= 6 and m['term'] >= 4 and m['Qd'] < 2
            and m['R'] < 6 and m['A'] < 2):
        return 'P2', [f"定义{m['D']} 术语{m['term']} 无对白（技术专著，非礼制条文）"], 'ok'
    if m['craft'] >= 20 and m['fank'] >= 1 and m['Qd'] < 2:
        return 'P2', [f"农工词{m['craft']}/千 凡字{m['fank']}/千（工艺专著）"], 'ok'
    # ---- P1 规范型 · 无编号体（礼制典籍） ----
    # 《礼记》《周礼》没有「第X条」，但通篇是「凡为人子之礼……」「凡与客入者……」
    # 的规范条文，与法规同类，产物也一样（规则卡 + 条目索引）。
    # 实测：周礼 凡式 7.5/万，礼记 0.8/万，其余 45 本全部 <=0.2/万。
    # 「凡」字频 礼记 4.2/千、周礼 5.0/千，其余 <=1.8/千（聊斋 0.4、史记 1.1）。
    if m['fan'] >= 0.5 or (m['fank'] >= 3 and m['R'] >= 5):
        return 'P1', [f"规范条文：凡式{m['fan']}/万 凡字{m['fank']}/千"], 'ok'
    if m['ping'] >= 20:
        return 'P9', [f"注评标记{m['ping']}处"], 'ok'
    # ---- P8 名物条目：山海经体例 ----
    # 旧 tm 轴把「又X里」与「有兽焉」混算，徐霞客（tm=1475 全是里程句）也判成条目型。
    # 拆开后 entx 只在山海经式文本成立（408 处），其余 33 本为 0~1。
    if m['entx'] >= 40:
        return 'P8', [f"名物条目句式{m['entx']}处（有X焉/曰X之山）"], 'ok'
    # ---- P7 韵文：句子短且等长 ----
    # 旧判据只看 smed<=17，把《天工开物》（smed=16 的技术书）也判成韵文集。
    # 韵文的核心不是「短」而是「等长」：mode2 = 句长落在最常见两个值上的比例。
    # 实测唐诗 70%、幼学琼林 41%、人间词话 25%，天工开物只有 12%。
    # 另加 citek<8 排除引书密的诗话（文心雕龙 13.4、随园诗话 12.6）。
    # 散曲（元曲三百首）句长因衬字不齐（mode2 仅 13%），但有 ○ 号曲牌，
    # 单独用「短句 + ○ 号密集 + 无对白」判。
    if ok_len and m['smed'] <= 15 and m['circ'] >= 20 and m['Q'] < 5:
        return 'P7', [f"○号曲牌{m['circ']}/万 句中位{m['smed']}字（散曲体）"], 'ok'
    # 关键约束（2026-11-07 盲测暴露）：文本若是**算法补的断句**，这一条不可用。
    # 白文古籍补断句后句子被人为压短压齐，三本散文（逸周书/三辅黄图/孔子家语）
    # 全部落进本区间被误判成韵文集。
    # 处理方式不是放宽阈值（那会漏掉真韵文），而是**要求标点可信**：
    # 标点不可信时，宁可让它走后面的分支或拒判，也不许凭空认定是韵文。
    # 唯一例外是有硬体例证据的（○ 号曲牌、可数的出目），那与标点无关。
    if (ok_len and not m['algo_punct']
            and m['smed'] <= 17 and m['mode2'] >= 25 and m['Q'] < 5
            and m['R'] < 8 and m['p3'] < 4 and m['citek'] < 8):
        return 'P7', [f"句中位{m['smed']}字 等长句占{m['mode2']}%"], 'ok'
    # ---- P3 语录体：先于叙事判 ----
    # 《论语》Qd=69.3、qpur=94，光看对白必被判成小说，实际是「子曰／XX曰」的
    # 对话语录，无场景、无人物动作、无情节推进。
    # 判据用「段首即说话人」的比例 yhead：语录体每一则都是独立问答，段首就是说话人；
    # 小说段落是连续描写，段首极少直接是「X曰」。
    # 实测 yhead：论语 61%、盐铁论 49%、孟子 35%、国语 14%；
    #   红楼梦 1%、金瓶梅 4%、三国 9%、史记 7%、聊斋 8%、文心雕龙 9%。取 20% 为界。
    # 用过但失败的判据（勿再试）：事件推进词密度（遂/乃/于是）——金瓶梅 1.3/千
    # 与论语 1.2 几乎相同，无法区分；场景描写词（笑道/只见/起身）——史记 0.0/千，
    # 文言叙事根本不用这些词，会把它误判成非叙事。
    if (m['Qd'] >= 30 and m['qpur'] >= 80 and m['yhead'] >= 20
            and m['A'] >= 1.0):
        return 'P3', [f"问答语录{m['Qd']}%（段首即说话人{m['yhead']}%）"], 'ok'
    # ---- P3 论辩体：先于叙事判 ----
    # 《盐铁论》《孟子》《国语》Qd 都在 40~70、qpur 都在 90 以上，
    # 光看对白会被判成小说；实际是「大夫曰／文学曰」「孟子对曰」式的长篇论辩，
    # 无场景、无动作。区分点是议论密度高（A=4.0~4.9，小说 0.5~2.0）
    # 且对白段长（盐铁论中位 103 字，小说 4~18 字）。
    # 用 4 本校准（盐铁论/孟子/国语/文心雕龙），非单样本。
    if m['A'] >= 4 and m['Qd'] >= 40 and m['R'] < 10:
        return 'P3', [f"议论{m['A']} 对白{m['Qd']}%（问答体政论，非叙事）"], 'ok'
    # ---- P4 叙事：用「真对白」而不是「引号总量」 ----
    # 旧判据用的 Q 把引书也算对白，于是考据书被误判成小说：
    #   日知录 Q=37.3 但 qpur=40%（《》6700 处，全是引经）
    #   随园诗话 Q=49.2 但引书 12.6/千、条目标题 43%（引诗评诗）
    # 四条通道覆盖不同写法，全部经 34 本实测校准：
    if m['Qd'] >= 18 and m['citek'] < 10 and m['qpur'] >= 55:
        return 'P4', [f"真对白{m['Qd']}% 引导词{m['qpur']}%（叙事体主导）"], 'ok'
    # 第二条：白话小说（《四世同堂》三册 p3=34~37）。
    # 门槛从 20 提到 28，因为 20~28 区间横跨 P4 与 P6 的真实边界：
    #   P6 散文最高 p3=18.0（野草），P4 叙事《四世同堂》最低 p3=34.2（上册）。
    # 18~34 之间是空的，取中间值 28 最稳。
    # 同时把 Qd 门槛从 6 降到 3：这一条的主判据是 p3（第三人称比例），
    # Qd 只用来排除「纯议论无对白」。《四世同堂·下册》Qd=6.5 贴着 6，
    # 扰动到 -8% 就掉下去，300 次里 76 次流向 P6。降到 3 后余量足够。
    # p3>=28 这一条本身极严（P6 八本最高 p3=18，离 28 差 10 个点），
    # 不会因为 Qd 放宽而误收散文。
    if m['Qd'] >= 3 and m['p3'] >= 28:
        return 'P4', [f"真对白{m['Qd']}% 第三人称{m['p3']}（白话小说）"], 'ok'
    if m['Qd'] >= 8 and m['p3'] >= 12 and m['A'] < 3.5:
        return 'P4', [f"真对白{m['Qd']}% 第三人称{m['p3']}"], 'ok'
    if (m['Qd'] >= 12 and ok_len and m['savg'] >= 18 and m['R'] < 5
            and m['A'] < 4 and m['citek'] < 3):
        return 'P4', [f"真对白{m['Qd']}% 句均长{m['savg']}（小说化改写）"], 'ok'
    # ---- P4 编年史（2026-11-08 新增） ----
    # 《左传》是叙事体，但它的对白全靠「书曰」「君子曰」引述、几乎不用引号，
    # 于是 Qd=0.0、p3=0.3，上面四条对白判据全部接不住。
    # 编年体的硬标志是**四季纪月**：「元年，春，王周正月」「夏四月」「秋，…」
    # 实测「[，。]春[，。]」密度：左传 1.3/千；史记 0.0、汉书 0.0、国语 0.0
    # —— 史家里只有编年体这么写，纪传体（史记/汉书）用「某年」不用四季。
    # 要求四季**同时出现**，避免把只是提到「春」的散文收进来。
    if m.get('season', 0) >= 0.5 and m['p1'] < 8:
        return 'P4', [f"四季纪月{m['season']}/千（编年体，叙事）"], 'ok'
    # ---- P3 论说 ----
    if m['R'] >= 12 and m['D'] >= 8:
        return 'P3', [f"规范{m['R']} 定义{m['D']}（概念+规则双强）"], 'ok'
    if m['A'] >= 3.5 and m['Qd'] < 8 and m['p3'] < 6:
        return 'P3', [f"议论{m['A']} 真对白仅{m['Qd']}%"], 'ok'
    if (m['R'] >= 8 and m['wen'] >= 25 and m['Qd'] < 8
            and m['p3'] < 5):
        return 'P3', [f"规范{m['R']} 文言{m['wen']}（方法论论著）"], 'ok'
    # ---- P2 知识型 ----
    if m['D'] >= 8 and m['Qd'] < 15:
        return 'P2', [f"定义{m['D']}"], 'ok'
    # 注：技术专著（D 6~8 且术语高）的判据已前置到 P1 之前，见上方注释。
    if ok_len and m['savg'] >= 28 and m['Qd'] < 8 and m['p3'] < 6 and m['term'] >= 5:
        return 'P2', [f"句均长{m['savg']} 术语{m['term']}（说明体）"], 'ok'
    # ---- P12 纪事型（人物故事 / 故事集 / 报告文学） ----
    # 这类书是叙事体，但叙述靠人名推进、不用「他/她」：
    # 国之脊梁 p3=8.4、河北廉洁故事 p3=10.0，都够不上 P4 的 p3>=28；
    # 第一人称又不够散文（p1 2.0/5.4），条目标题也不够笔记（entp 0.1/3.2）。
    # 判据只用四条：有对白、第一人称少、长句、没有条目标题。
    # 实测 60 本里只命中这两本，其余零误伤。
    # 必须放在 P6 之前：p1 5.4 贴着 P6 的 6，放后面在阈值扰动时会被 P6 抢走。
    if (m['Q'] >= 10 and m['p1'] < 8 and m['savg'] >= 26
            and m['p3'] < 28 and m['entp'] < 20):
        return 'P12', [f"对白{m['Q']}% 第一人称{m['p1']} 句均{m['savg']}（人物故事体）"], 'ok'

    # ---- P6 散文 ----
    if m['p1'] >= 8 and m['Q'] >= 3:
        return 'P6', [f"第一人称{m['p1']} 对白{m['Q']}%"], 'ok'
    if m['p1'] >= 6:
        return 'P6', [f"第一人称{m['p1']}（记述体）"], 'ok'
    # ---- P10 笔记志书型 ----
    # 这类书的特征是「三样都有但都不占优」：有引书却不成论、有叙事却无对白、
    # 句子短却不押韵。旧实现里它们全部拒判或误判成叙事。
    # 实测命中：随园诗话（条目 43%）、陶庵梦忆（42%）、东京梦华录（29%）、
    # 日知录（圈号 26/万 + 引书 17/千）、梦溪笔谈（引书 5/千）、
    # 徐霞客（处所名物 102/千）。
    #
    # P10 是**兜底类**，必须排在所有主动特征之后，且自身不能抢别的类。
    # 踩过的坑：《元曲三百首》citek=4.0 正好贴在「引书>=4」门槛上，
    # 扰动时反复越线，300 次里有 17 次被抢判成 P10，稳定性从 100% 掉到 83%。
    # 它是散曲集（circ=89/万、句长13字），已被 P7 正确认领，P10 不该再伸手。
    # 因此「引书」这一条必须排除「已有强体例证据」的书：
    #   有 ○ 号曲牌（circ>=15）→ 是散曲，不是笔记；
    #   有真对白且是叙事（Qd>=10 且 p3>=12）→ 是小说，不是笔记。
    _why = []
    if m['entp'] >= 20:
        _why.append(f"条目标题{m['entp']}%")
    if m['circ'] >= 15 and m['entp'] >= 10:
        _why.append(f"圈号条目{m['circ']}/万")
    if (m['citek'] >= 4 and m['R'] < 8 and (not ok_len or m['savg'] < 25)
            and m['circ'] < 15 and not (m['Qd'] >= 10 and m['p3'] >= 12)):
        _why.append(f"引书{m['citek']}/千")
    if m['plac'] >= 80 and m['p1'] < 2:
        _why.append(f"处所名物{m['plac']}/千")
    if _why:
        return 'P10', ["笔记体：" + ' '.join(_why)], 'ok'
    # 主动特征全部不成立 —— 拒绝归类，不再兜底塞进 P6
    return None, [f"拒判·主动特征全不成立"
                  f"(p1={m['p1']} Qd={m['Qd']} qpur={m['qpur']} R={m['R']} "
                  f"D={m['D']} savg={m['savg']} smed={m['smed']} "
                  f"mode2={m['mode2']} entp={m['entp']} citek={m['citek']})"], 'unknown'


# ---------- 置信度：实测抗扰动率，不是分支上的固定标签 ----------
# 把 judge 的全部数值阈值参数化，随机浮动 ±20% 后重判，重复 N 次，
# 「判型不变」的比例就是这本书的稳定性。这个量能复算、能复现（种子绑书量），
# 且不依赖我手工给哪条分支标「高」还是「中」。
THR = {
    # 体例轴
    'jb8': 8, 'chu': 8, 'kejie': 20, 'tiao': 20, 'ping': 20, 'entx40': 40,
    'alb2': 2, 'Q10': 10, 'p1x8': 8, 'savg27': 26,
    'fan05': 0.5, 'fank3': 3, 'R5b': 5,
    # 韵文
    'smed15': 15, 'circ20': 20, 'Q5': 5, 'smed17': 17, 'mode25': 25,
    'R8': 8, 'p3x4': 4, 'citek8': 8,
    # 论辩
    'A4': 4, 'Qd40': 40, 'R10': 10,
    # 语录体
    'Qd30': 30, 'qpur80': 80, 'yhead20': 20, 'A10': 1.0,
    # 叙事
    'Qd18': 18, 'citek10': 10, 'qpur55': 55,
    'Qd3': 3, 'p3x28': 28,
    'Qd8': 8, 'p3x12': 12, 'A35': 3.5,
    'Qd12': 12, 'savg18': 18, 'R5': 5, 'A4b': 4, 'citek3': 3,
    # 论说
    'R12': 12, 'D8': 8,
    'A35b': 3.5, 'Qd8b': 8, 'p3x6': 6,
    'R8b': 8, 'wen25': 25, 'p3x5': 5,
    # 知识
    'D8b': 8, 'Qd15': 15,
    'D6': 6, 'Qd2': 2, 'A2': 2, 'R6': 6, 'term4': 4, 'craft20': 20, 'fank1': 1,
    'savg28': 28, 'term5': 5,
    # 散文
    'p1x8': 8, 'Q3': 3, 'p1x6': 6,
    # 笔记体
    'entp20': 20, 'circ15': 15, 'entp10': 10,
    'citek4': 4, 'savg25': 25, 'plac80': 80, 'p1x2': 2, 'Qd10': 10,
    # 2026-11-08 新增（词典体 / 编年史）
    'yek30': 30, 'season05': 0.5,
}
STABLE_PCT = 0.20   # 扰动幅度。±10%~±15% 的排名一致性 rho=+0.81，再放大掉到 +0.47，
                    # 说明 ±20% 接近本测量的分辨率上限。
STABLE_N = 300      # 采样次数。n=100 与 n=1000 结果差不到 5 个百分点，300 够用。
                    # 实测单本约 1 毫秒，22 本合计 0.03 秒。


def _judge_th(m, th):
    """与 judge 同结构的判定，但阈值全部来自 th。只用于稳定性采样。
    注意：这里刻意**不含 gate**，因为 gate 只看文本本身、不受阈值影响。
    必须与 judge 的分支顺序、条件一一对应，否则「稳定性」测的不是判型本身。
    维护约定：judge 里加一条分支，这里必须同步加一条，否则稳定性会虚高。"""
    # 与 judge 同口径：句长指标不可信时，凡用到它的分支一律回避。
    # 漏掉这一行会让尔雅/左传的稳定性算成 0%（实测过），因为
    # 采样时它们走的判据与真实判型不一致。
    _g, _bad = gate(m)
    ok_len = not ({'savg', 'smed', 'mode2'} & set(_bad))
    # P11 图鉴（与 judge 同序，必须最前）
    if m.get('alb', 0) >= th['alb2']:
        return 'P11'
    # P8 词典体（与 judge 同序，必须最前）
    if m.get('yek', 0) >= th['yek30'] and m['Qd'] < th['Q5']:
        return 'P8'
    if m['jb'] >= th['jb8']:
        return 'P5'
    if m['chu'] >= th['chu'] and m['kejie'] >= th['kejie']:
        return 'P5'
    if m['tiao'] >= th['tiao']:
        return 'P1'
    # P2 技术专著（前置，与 judge 同序）
    if (m['D'] >= th['D6'] and m['term'] >= th['term4']
            and m['Qd'] < th['Qd2'] and m['R'] < th['R6'] and m['A'] < th['A2']):
        return 'P2'
    if m['craft'] >= th['craft20'] and m['fank'] >= th['fank1'] and m['Qd'] < th['Qd2']:
        return 'P2'
    if m['fan'] >= th['fan05'] or (m['fank'] >= th['fank3'] and m['R'] >= th['R5b']):
        return 'P1'
    if m['ping'] >= th['ping']:
        return 'P9'
    if m['entx'] >= th['entx40']:
        return 'P8'
    if ok_len and m['smed'] <= th['smed15'] and m['circ'] >= th['circ20'] and m['Q'] < th['Q5']:
        return 'P7'
    if (ok_len and not m['algo_punct']
            and m['smed'] <= th['smed17'] and m['mode2'] >= th['mode25']
            and m['Q'] < th['Q5'] and m['R'] < th['R8'] and m['p3'] < th['p3x4']
            and m['citek'] < th['citek8']):
        return 'P7'
    if (m['Qd'] >= th['Qd30'] and m['qpur'] >= th['qpur80']
            and m['yhead'] >= th['yhead20'] and m['A'] >= th['A10']):
        return 'P3'
    if m['A'] >= th['A4'] and m['Qd'] >= th['Qd40'] and m['R'] < th['R10']:
        return 'P3'
    if (m['Qd'] >= th['Qd18'] and m['citek'] < th['citek10']
            and m['qpur'] >= th['qpur55']):
        return 'P4'
    if m['Qd'] >= th['Qd3'] and m['p3'] >= th['p3x28']:
        return 'P4'
    if m['Qd'] >= th['Qd8'] and m['p3'] >= th['p3x12'] and m['A'] < th['A35']:
        return 'P4'
    if (m['Qd'] >= th['Qd12'] and ok_len and m['savg'] >= th['savg18']
            and m['R'] < th['R5'] and m['A'] < th['A4b']
            and m['citek'] < th['citek3']):
        return 'P4'
    if m.get('season', 0) >= th['season05'] and m['p1'] < th['p1x8']:
        return 'P4'
    if m['R'] >= th['R12'] and m['D'] >= th['D8']:
        return 'P3'
    if m['A'] >= th['A35b'] and m['Qd'] < th['Qd8b'] and m['p3'] < th['p3x6']:
        return 'P3'
    if (m['R'] >= th['R8b'] and m['wen'] >= th['wen25']
            and m['Qd'] < th['Qd8b'] and m['p3'] < th['p3x5']):
        return 'P3'
    if m['D'] >= th['D8b'] and m['Qd'] < th['Qd15']:
        return 'P2'
    # 注：技术专著（D 6~8 且术语高）已前置到 P1 之前，此处不再重复。
    if (ok_len and m['savg'] >= th['savg28'] and m['Qd'] < th['Qd8b']
            and m['p3'] < th['p3x6'] and m['term'] >= th['term5']):
        return 'P2'
    if (m['Q'] >= th['Q10'] and m['p1'] < th['p1x8'] and m['savg'] >= th['savg27']
            and m['p3'] < th['p3x28'] and m['entp'] < th['entp20']):
        return 'P12'
    if m['p1'] >= th['p1x8'] and m['Q'] >= th['Q3']:
        return 'P6'
    if m['p1'] >= th['p1x6']:
        return 'P6'
    if (m['entp'] >= th['entp20']
            or (m['circ'] >= th['circ15'] and m['entp'] >= th['entp10'])
            or (m['citek'] >= th['citek4'] and m['R'] < th['R8']
                and (not ok_len or m['savg'] < th['savg25'])
                and m['circ'] < th['circ15']
                and not (m['Qd'] >= th['Qd10'] and m['p3'] >= th['p3x12']))
            or (m['plac'] >= th['plac80'] and m['p1'] < th['p1x2'])):
        return 'P10'
    return None


def stability(m, base, pct=STABLE_PCT, n=STABLE_N, seed=0):
    """阈值随机扰动 ±pct，重复 n 次，返回判型不变的比例（0~1）。
    种子绑实测特征值，保证同一本书重跑得同一个数 —— 满足「连跑两次一致」。"""
    import random
    rnd = random.Random('%d|%d|%d' % (m['h'], int(m['savg'] * 10), seed))
    same = 0
    for _ in range(n):
        th = {k: v * (1 + rnd.uniform(-pct, pct)) for k, v in THR.items()}
        if _judge_th(m, th) == base:
            same += 1
    return same / float(n)


def conf_of(st):
    """稳定性 → 三档。阈值由 22 本实测分布定：
       100% 的归「高」，90%~100% 归「中」，<90% 归「低」。
    实测分布：22 本里 16 本为 100%，最低的两本是 52%（四月天文学卷）、84%（建筑卷）。"""
    if st >= 0.995:
        return '高'
    if st >= 0.90:
        return '中'
    return '低'


def _ratio_ge(v, T):
    """越大越好的条件。1.0 = 刚好达到阈值。"""
    return 2.0 if T <= 0 else min(v / T, 2.0)


def _ratio_lt(v, T):
    """必须小于阈值的条件。v=0 最理想，余量封顶 2.0；v 贴着上限则接近 1.0。"""
    if v <= 0:
        return 2.0
    if T <= 0:
        return 1.0
    return min(T / v, 2.0)


def _ret(code, ev, m, key=None):
    """保留签名供各分支调用。置信度不在这里定，由 analyze() 用实测稳定性重算。"""
    return code, list(ev), None


INCOMPAT = {
    'P4': {'P7', 'P8', 'P9', 'P1', 'P2', 'P10'},
    'P5': {'P7', 'P8', 'P1', 'P2', 'P10'},
    'P6': {'P7', 'P8', 'P1', 'P2', 'P5', 'P10'},
    'P7': {'P1', 'P2', 'P3', 'P4', 'P5', 'P8', 'P10'},
    'P8': {'P1', 'P2', 'P3', 'P4', 'P5', 'P10'},
    'P9': {'P1', 'P2', 'P10'},
    'P3': {'P1', 'P7', 'P8', 'P10'},
    'P2': {'P4', 'P5', 'P7', 'P10'},
    'P1': {'P4', 'P5', 'P6', 'P7', 'P10'},
    'P10': {'P4', 'P5', 'P7', 'P1', 'P2'},
    'P11': {'P8', 'P10', 'P2'},
    'P12': {'P4', 'P6', 'P10'},
}


def gate_chunk(m):
    """分块判定用的门。只保留与体量无关的两项检查（汉字率、句读），
    不检查 MIN_HAN —— MIN_HAN=8000 是「整本书」的下界，一块只有几千字，
    若沿用会把每一块都拒掉。这正是此前「22 本分块投票全是 None」的原因。"""
    if m['han_ratio'] < MIN_HAN_RATIO:
        return ('非中文文本', f"文字中汉字仅占{m['han_ratio']}%")
    if m['savg'] > MAX_SAVG:
        return ('句读缺失', f"句均长{m['savg']}字")
    if m['lmed'] <= 8 and m['smed'] <= 8:
        return ('词条排版', f"行中位长{m['lmed']}字")
    return None


CHUNK_MIN_HAN = 1500   # 分块判型的最低汉字数。低于此句长统计不稳，
                       # 但远低于 8000，保证 5~10 块都能出声。

# 格式轴（绝对计数类）在分块时必须按体量折算，否则小块永远达不到整书的阈值。
# 实测：牡丹亭整本 chu=110/qupai=478/kejie=857，切成 10 块后每块只有
# chu=2~7，于是 6 块被判「什么都判不出」。这不是书不统一，是判据没折算。
# 折算方式：把阈值按「块汉字数 / 整本汉字数」等比缩小。这是量纲正确的做法，
# 因为它假设「同样的排版密度」，而不是「同样的绝对数量」。
ABS_AXES = ('tm', 'chu', 'qupai', 'kejie', 'tiao', 'ping', 'entx')
# 密度轴（jb/entp/circ/citek 已按每万/每千字或百分比归一）不折算，
# 但它们在不同体量下的小样本噪声更大 —— 折算只对绝对计数有意义。


def chunk_thr(m_chunk, m_whole):
    """把整本阈值折算到分块体量。密度轴（Q/p3/R/savg…）是比率，不折算。

    关键约束（踩过两次）：
      1. 整本该轴为 0 时不能折成小阈值，否则《元曲三百首》（整本 qupai=0）
         某个块凑出 5 个【】就被判成 P5 戏曲型 —— 凭空造出混入。
      2. 更隐蔽的一条：整本该轴不达阈值时，也不能折算。
         《元曲三百首》整本 chu=3 < 8，本体不成立；但切成 10 块后阈值降到 1，
         一块里恰好出现 1 个「第X出」就判 P5。这是把噪声放大成证据。
    规则：某一轴只有在**整本层面已经成立**时，才允许在分块里折算使用；
    整本不成立 → 该轴在分块里禁用（阈值设 inf）。
    """
    ratio = m_chunk['h'] / float(max(1, m_whole['h']))
    th = dict(THR)
    for k in ABS_AXES:
        if k in th:
            base = m_whole.get(k, 0)
            if base < THR[k]:             # 整本都不够格 → 该轴对本块不适用
                th[k] = float('inf')
            else:
                th[k] = max(1.0, THR[k] * ratio)
    return th


def chunk_votes(text, n=10, min_han=CHUNK_MIN_HAN, m_whole=None):
    """分块判型，用于识别混合集。

    修正（2026-11-07）三处：
      1. 旧实现直接调 judge()，而 judge 内含 gate()，gate 的 MIN_HAN=8000
         是按整本书定的 —— 每块都被判「样本不足」，22 本分块投票全是 None，
         混合检测形同不存在。《四月天·文学卷》40% 是小说却报「无混入」。
      2. 格式轴是绝对计数，不按体量折算则小块永远不达阈值（牡丹亭 6/10 块判空）。
      3. 改用 density 折算后的阈值，判据量纲统一。
    """
    body = re.sub(r'<<<PAGE \d+>>>', '\n', text)
    N = len(body)
    if m_whole is None:
        m_whole = measure(text)
    votes = []
    for i in range(n):
        seg = body[i * N // n:(i + 1) * N // n]
        m = measure(seg)
        if m['h'] < min_han:
            continue
        if gate_chunk(m):
            continue
        votes.append(_judge_th(m, chunk_thr(m, m_whole)))
    return votes


def analyze(text, algo_punct=False):
    m = measure(text, algo_punct=algo_punct)
    code, ev, kind = judge(m)
    # 体量不足：判型结论仍给，但置信度封顶为「低」。
    # 这是 2026-11-08 的改动：茶经、诗品这类短底本不再被拒判，
    # 但也不能对外说「判得很准」—— 5771 字的语体统计本来就不足采信。
    _conf_cap = '低' if m['h'] < MIN_HAN else None
    if code is not None:
        st = stability(m, code)
        conf = conf_of(st)
        if _conf_cap:
            conf = _conf_cap
        ev = ev + [f"稳定性{st*100:.0f}%"]
        if _conf_cap:
            ev = ev + [f"底本体量{m['h']}字<{MIN_HAN}，置信度按低档处理，"
                       f"结论仅供参照，不宜横向比较"]
    else:
        st = None
        conf = '无'
    votes = chunk_votes(text, m_whole=m)
    from collections import Counter
    mixed = []
    if votes and code is not None:
        cnt = Counter(votes)
        # 混入的判据：任一块判成「与主判不同且互斥」的类，块数 ≥1 就报。
        # 旧实现要求「主判占比<80% 且混入块≥2」，等于先要求主判自己不稳，
        # 才肯承认混入 —— 《四月天·文学卷》主判占 5/10 时能报，
        # 但一本 80% 散文 + 20% 小说的集子会永远报不出来。
        # 现在的口径是「只要有一部分明显是另一类，就如实标出」。
        mixed = [(c, round(v * 100.0 / len(votes)))
                 for c, v in cnt.most_common()
                 if c and c != code and c in INCOMPAT.get(code, set())]
    mixed.sort(key=lambda x: -x[1])
    # 主判在分块中的占比：比 mixed 更硬的一条证据。
    # 一本书如果只有 40% 的块判成主判类，那么「整本属于这一类」这句话本身
    # 就不该说出口。《四月天·文学卷》正是如此（P6 占 4/10）。
    favg = None
    if votes and code is not None:
        favg = round(sum(1 for v in votes if v == code) * 100.0 / len(votes))
    # 合集构成：书中自己写明了多种文体时，如实报构成，不用单一原型概括。
    sec = sections(text)
    anth = []
    if len(sec) >= 2:
        tot = sum(h for _, _, h in sec) or 1
        anth = [(n, round(h * 100.0 / tot)) for n, _, h in sec]
        top = max(anth, key=lambda x: x[1])
        ev = ev + [f"合集：{len(anth)} 种文体，占比最大为{top[0]}{top[1]}%"]
    if code is None:
        # 拒判：不声明任何产物，由页面显示原因
        # kind='data'    → 文本不可用，补数据重试，不算遇到新类型
        # kind='unknown' → 数据可用但九类全不成立，疑似第十类，需人工判断
        return {'m': m, 'code': None, 'arch': '待开原型',
                'outputs': [], 'ev': ev, 'conf': conf, 'stability': None,
                'reject_kind': kind, 'votes': votes, 'mixed': mixed,
                'anthology': anth, 'fit': favg}
    return {'m': m, 'code': code, 'arch': ARCH[code][0],
            'outputs': ARCH[code][1], 'ev': ev, 'conf': conf,
            'stability': st, 'votes': votes, 'mixed': mixed,
            'anthology': anth, 'fit': favg}


if __name__ == '__main__':
    import io, glob, os, json
    from collections import Counter
    RAW = P.RAW
    res = []
    for p in sorted(glob.glob(RAW + '/*.txt')):
        b = os.path.basename(p)[:-4]
        if b.startswith('_'):
            continue
        t = io.open(p, encoding='utf-8', errors='replace').read()
        r = analyze(t)
        r['book'] = b
        res.append(r)
    res.sort(key=lambda x: -x['m']['h'])
    print(f"{'书':<22}{'字':>8}{'原':<4}{'置信':<4}{'均句':>5}{'他她':>6}"
          f"{'对白':>5}{'文言':>5}{'规范':>5}{'定义':>5}{'议论':>5}  依据")
    print('-' * 118)
    for r in res:
        m = r['m']
        print(f"{r['book'][:20]:<22}{m['h']:>8}{r['code']:<4}{r['conf']:<4}"
              f"{m['savg']:>5}{m['p3']:>6}{m['Q']:>5}{m['wen']:>5}"
              f"{m['R']:>5}{m['D']:>5}{m['A']:>5}  {r['ev'][0]}")
        if r['mixed']:
            print(f"{'':24}混合: {r['mixed']}")
    print('\n=== 原型分布 ===')
    for code, v in Counter(r['code'] for r in res).most_common():
        names = [r['book'][:10] for r in res if r['code'] == code]
        print(f"{code} {ARCH[code][0]:<8}{v:>3} 本  {'、'.join(names)}")
    print(f"\n合计 {len(res)} 本 {sum(r['m']['h'] for r in res):,} 汉字")
    json.dump([{k: v for k, v in r.items() if k != 'votes'} for r in res],
              io.open(os.path.join(P.OUT, 'measure.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('已写出 out/measure.json')
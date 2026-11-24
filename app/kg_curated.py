"""Small, source-checked graph examples; no generated or source files are changed.

IDs describe facts rather than their current wording. Each fact is admitted only
while its literal excerpt and chapter still match the current source paragraph.
"""

NODES = {
    'B59': {
        'P-李四光': {'label': '李四光', 'type': '人物', 'existing': True},
        'P-茅以升': {'label': '茅以升', 'type': '人物', 'existing': True},
        'P-谢家麟': {'label': '谢家麟', 'type': '人物', 'existing': True},
        'P-裴文中': {'label': '裴文中', 'type': '人物', 'existing': True},
        'P-王应睐': {'label': '王应睐', 'type': '人物', 'existing': True},
        'P-汪猷': {'label': '汪猷', 'type': '人物', 'existing': True},
        'P-叶企孙': {'label': '叶企孙', 'type': '人物', 'existing': True},
        'P-华罗庚': {'label': '华罗庚', 'type': '人物', 'existing': True},
        'P-钱学森': {'label': '钱学森', 'type': '人物', 'existing': True},
        'P-郭永怀': {'label': '郭永怀', 'type': '人物', 'existing': True},
        'EV-LUSHAN-GLACIER': {'label': '庐山冰川研究', 'type': '事件'},
        'PR-QIANTANG-BRIDGE': {'label': '钱塘江大桥', 'type': '工程'},
        'PR-BEIJING-COLLIDER': {'label': '北京正负电子对撞机', 'type': '工程'},
        'EV-ZHOUKOUDIAN': {'label': '周口店北京猿人遗址发掘与研究', 'type': '事件'},
        'PR-INSULIN-SYNTHESIS': {'label': '胰岛素人工合成研究', 'type': '工程'},
    },
    'B66': {
        'CON-DIFFERENTIAL-ORDER': {'label': '差序格局', 'type': '概念'},
        'CASE-NEIGHBORHOOD-HELP': {'label': '街坊互助', 'type': '案例',
                                   'desc': '作者用来说明社会圈子伸缩的生活例子，并非某一户的实名个案。'},
        'CON-RITUAL-ORDER': {'label': '礼治秩序', 'type': '概念'},
        'CASE-VILLAGE-MEDIATION': {'label': '乡公所调解家庭纠纷', 'type': '案例',
                                    'desc': '作者亲历并记录的乡村评理个案，原文以某甲等代称人物。'},
        'CON-GROUP-ORDER': {'label': '团体格局', 'type': '概念'},
        'CASE-MONEY-ASSOCIATION': {'label': '钱会（信用互助组织）', 'type': '案例',
                                   'desc': '作者明确归于团体格局的钱会，并记录了参与者关系的调查。'},
    },
}

FACTS = {
    'B59': (
        {'id': 'CE-LSG-LUSHAN-RESEARCH', 'source': 'P-李四光', 'target': 'EV-LUSHAN-GLACIER',
         'rel': '投入研究', 'anchor': 'B59-01-P05', 'chapter': '李四光',
         'quote': '他还考察了庐山、黄山等地，后来干脆把家搬到了庐山上，全身心投入到冰川研究中。'},
        {'id': 'CE-MYS-QIANTANG-CONSTRUCTION', 'source': 'P-茅以升', 'target': 'PR-QIANTANG-BRIDGE',
         'rel': '主持修建', 'anchor': 'B59-03-P01', 'chapter': '茅以升',
         'quote': '主持修建了我国首座跨度较大的钱塘江公路铁路两用桥和武汉长江大桥。'},
        {'id': 'CE-MYS-QIANTANG-RESTORATION', 'source': 'P-茅以升', 'target': 'PR-QIANTANG-BRIDGE',
         'rel': '受命修复', 'anchor': 'B59-03-P12', 'chapter': '茅以升',
         'quote': '抗战胜利后，茅以升受命修复大桥。', 'required': ('钱塘江大桥',)},
        {'id': 'CE-XJL-BEIJING-COLLIDER', 'source': 'P-谢家麟', 'target': 'PR-BEIJING-COLLIDER',
         'rel': '领导设计、研制和建造', 'anchor': 'B59-35-P01', 'chapter': '谢家麟',
         'quote': '领导了北京正负电子对撞机工程的设计、研制和建造'},
        {'id': 'CE-PWZ-ZHOUKOUDIAN', 'source': 'P-裴文中', 'target': 'EV-ZHOUKOUDIAN',
         'rel': '主持并参与', 'anchor': 'B59-08-P01', 'chapter': '裴文中',
         'quote': '主持并参与周口店北京猿人遗址的发掘和研究工作'},
        {'id': 'CE-WYL-INSULIN-LEAD', 'source': 'P-王应睐', 'target': 'PR-INSULIN-SYNTHESIS',
         'rel': '担任研究组长', 'anchor': 'B59-11-P11', 'chapter': '王应睐',
         'quote': '王应睐是人工合成胰岛素和人工合成核糖核酸的组长。'},
        {'id': 'CE-WY-INSULIN-PARTICIPATION', 'source': 'P-汪猷', 'target': 'PR-INSULIN-SYNTHESIS',
         'rel': '参与领导并直接参加', 'anchor': 'B59-13-P01', 'chapter': '汪猷',
         'quote': '参与领导并直接参加了“人工全合成结晶牛胰岛素”和“酵母丙氨酸转移核糖核酸的人工全合成”两个重大项目。'},
        {'id': 'CE-YQS-HLG-TEACHING', 'source': 'P-叶企孙', 'target': 'P-华罗庚',
         'rel': '推动破格任教', 'anchor': 'B59-04-P05', 'chapter': '叶企孙',
         'quote': '欣喜之余，叶企孙与熊庆来、杨武之等数学系领导商议，决定破格提升华罗庚为教员。'},
        {'id': 'CE-QXS-GYH-GUIDANCE', 'source': 'P-钱学森', 'target': 'P-郭永怀',
         'rel': '协助指导', 'anchor': 'B59-12-P03', 'chapter': '郭永怀',
         'quote': '而协助冯·卡门指导郭永怀的，则是时任加州理工学院副教授的钱学森。'},
    ),
    'B66': (
        {'id': 'CE-DIFFERENTIAL-NEIGHBORHOOD', 'source': 'CON-DIFFERENTIAL-ORDER',
         'target': 'CASE-NEIGHBORHOOD-HELP', 'rel': '以街坊互助说明',
         'anchor': 'B66-07-P09', 'chapter': '差序格局',
         'quote': '在传统结构中，每一家以自己的地位作中心，周围划出一个圈子，这个圈子是“街坊”。有喜事要请酒，生了孩子要送红蛋，有丧事要出来助殓，抬棺材，是生活上的互助机构。',
         'support_evidence': [
             {'anchor': 'B66-07-P09', 'chapter': '差序格局',
              'quote': '中国传统结构中的差序格局具有这种伸缩能力。'},
         ]},
        {'id': 'CE-RITUAL-MEDIATION', 'source': 'CON-RITUAL-ORDER',
         'target': 'CASE-VILLAGE-MEDIATION', 'rel': '以乡村调解说明',
         'basis': 'interpretation',
         'anchor': 'B66-12-P06', 'chapter': '无讼',
         'quote': '家里大闹起来，被人拉到乡公所来评理。那位乡绅，先照例认为这是件全村的丑事。接着动用了整个伦理原则：',
         'required': ('大家认了罚回家',),
         'support_evidence': [
             {'anchor': 'B66-12-P04', 'chapter': '无讼',
              'quote': '所谓礼治就是对传统规则的服膺。'},
             {'anchor': 'B66-12-P05', 'chapter': '无讼',
              'quote': '在乡村里所谓调解，其实是一种教育过程。我曾在乡下参加过这类调解的集会。'},
         ]},
        {'id': 'CE-GROUP-MONEY-ASSOCIATION', 'source': 'CON-GROUP-ORDER',
         'target': 'CASE-MONEY-ASSOCIATION', 'rel': '以钱会为例',
         'anchor': 'B66-09-P01', 'chapter': '家族',
         'quote': '显然是属团体格局的', 'required': ('譬如钱会',),
         # Keep separate literal excerpts around a damaged footnote; do not
         # manufacture a continuous quotation by silently correcting “即1”.
         'support_evidence': [
             {'anchor': 'B66-09-P01', 'chapter': '家族', 'quote': '譬如钱会'},
             {'anchor': 'B66-15-P13', 'chapter': '血缘和地缘',
              'quote': '钱会，是一种信用互助组织。我调查了参加的人的关系，看到两种倾向，第一是避免同族的亲属，第二是侧重在没有亲属关系的朋友方面。'},
         ]},
    ),
}

# These are editorial connections between two independently sourced contexts,
# not graph_relation assets or claims that the endpoint entities are identical.
# Pin the complete paragraphs as well as the excerpts: a changed context needs
# another review even when the short quotation happens to remain unchanged.
CROSS_LINKS = (
    {'id': 'XL-B59-YC-LUXUN', 'label': '经鲁迅关联', 'title': '裴文中的文学经历与鲁迅《野草》',
     'source': 'B59:P-裴文中', 'source_label': '裴文中', 'target': 'YC:C-题辞', 'target_label': '题辞',
     'basis': '共同人物', 'via': '鲁迅',
     'reason': '《国之脊梁》记载鲁迅赞赏裴文中的小说《戎马声中》；《野草》题辞以鲁迅署名。两处材料分别呈现鲁迅与青年作者、与自身作品的联系。',
     'evidence': [
         {'code': 'B59', 'anchor': 'B59-08-P08', 'chapter': '裴文中',
          'quote': '他写了好几篇小说和散文，其中一篇小说《戎马声中》还受到了鲁迅的赞赏。',
          'sha256': 'c23fa919ab65a1a914d7bb1088d274cdfdcd34ca7ef3b63846ad05967503b6a7'},
         {'code': 'YC', 'anchor': 'YC-01-P02', 'chapter': '题辞',
          'quote': '去罢，野草，连着我的题辞！一九二七年四月二十六日鲁迅记于广州之白云楼上',
          'sha256': 'e75b7ac1cfab10f20ae55802910a2bb1740844d49aae839de87115800c6d5aeb'},
     ]},
    {'id': 'XL-B59-B66-SOUTHWEST-UNIVERSITY', 'label': '西南联大', 'title': '两书中的西南联大经历',
     'source': 'B59:P-叶企孙', 'source_label': '叶企孙', 'target': 'B66:C-后记', 'target_label': '后记',
     'basis': '共同机构', 'via': '西南联大',
     'reason': '以西南联大为共同机构，串联《国之脊梁》中叶企孙的教学与《乡土中国》后记中的工作自述。',
     'evidence': [
         {'code': 'B59', 'anchor': 'B59-04-P06', 'chapter': '叶企孙',
          'quote': '抗战爆发后，清华大学和北京大学、南开大学合并成国立西南联合大学，西迁到了昆明。炮火纷飞下，叶企孙仍然坚持讲授电磁学课程。',
          'sha256': 'e82ea5163537174fc62330bad110baf779c7ad8bc33c972afdedb557fe1e2d7c'},
         {'code': 'B66', 'anchor': 'B66-18-P43', 'chapter': '后记',
          'quote': '所以我只能取道越南回国，到达昆明，在当时的云南大学和由清华、北大、南开联合的西南联大工作。',
          'sha256': '553106e644fb5eb6a798bc9526079aa1b583e6270615646005819448f8726901'},
     ]},
)

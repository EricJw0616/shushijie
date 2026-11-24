"""Validate a video handoff script and derive all reading views from one timeline."""
import re
import math


def validate_narration_budget(production, expected_duration=None):
    """An editorial capacity limit for new Chinese drafts, never an audio measurement.

    Callers decide whether this policy applies to a newly generated version.
    Saved or confirmed manuscripts are not rewritten or truncated here.
    """
    if not isinstance(production, dict) or not isinstance(production.get('shots'), list):
        raise ValueError('口播稿缺少可统计的段落。')
    duration = production.get('duration_seconds') if expected_duration is None else expected_duration
    if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
            not math.isfinite(duration) or not 0 < duration <= 600):
        raise ValueError('口播初稿预算需要有效的用户计划时长。')
    voices = []
    for shot in production['shots']:
        if not isinstance(shot, dict) or not isinstance(shot.get('voiceover'), str):
            raise ValueError('口播段落格式无效，无法核对初稿预算。')
        voices.append(shot['voiceover'])
    text = ''.join(voices)
    count = sum(character.isalnum() for character in text)
    chinese = len(re.findall(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]', text))
    limit = math.floor(duration * 4)
    stats = {'applies': chinese > 0 and chinese * 2 >= count, 'characters': count,
             'chinese_characters': chinese, 'duration_seconds': duration,
             'limit': limit, 'kind': 'editorial_character_budget'}
    if stats['applies'] and count > limit:
        raise ValueError('中文口播初稿含%d个汉字及字母数字字符（标点空白不计），%g秒编辑预算上限为%d个；'
                         '这是初稿容量规范，不是实测语速。请压缩非核心内容，保持表达完整，不机械截断、不增加计划时长。' %
                         (count, duration, limit))
    return stats


def _text(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError('视频制作稿的%s缺失或过长，请重新生成。' % label)
    # Fields describe one shot/asset; headings belong to the canonical renderer.
    return ' '.join(value.split())


def _seconds(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= 600:
        raise ValueError('视频制作稿的%s应为有效整数秒。' % label)
    return value


def validate(value, audience=None, require_prompts=True, include_prompts=True):
    if not isinstance(value, dict):
        raise ValueError('短视频缺少完整制作稿，请重新生成。')
    duration = _seconds(value.get('duration_seconds'), '计划时长', 15)
    ratio = _text(value.get('aspect_ratio'), '画幅', 12)
    if not re.fullmatch(r'[1-9]\d?:[1-9]\d?', ratio):
        raise ValueError('视频画幅应使用9:16等比例。')
    result = {'format': _text(value.get('format'), '制作方式', 40),
              'duration_seconds': duration, 'aspect_ratio': ratio, 'materials': [], 'shots': []}
    with_prompts = include_prompts and (require_prompts or 'visual_style' in value)
    if with_prompts:
        # The project brief is authoritative; generated text cannot redefine the viewer.
        result['audience'] = _text(audience if audience is not None else value.get('audience'), '最终观众', 800)
        result['visual_style'] = _text(value.get('visual_style'), '统一视觉风格', 1200)
    materials = value.get('materials')
    if not isinstance(materials, list) or not 1 <= len(materials) <= 24:
        raise ValueError('视频制作稿应列出需要准备的具体画面素材。')
    identifiers = set()
    for item in materials:
        if not isinstance(item, dict):
            raise ValueError('画面素材格式无效。')
        identifier = _text(item.get('id'), '画面素材编号', 40)
        if identifier in identifiers or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', identifier):
            raise ValueError('画面素材编号重复或无效。')
        identifiers.add(identifier)
        result['materials'].append({'id': identifier, 'name': _text(item.get('name'), '素材名称', 100),
                                    'source': _text(item.get('source'), '素材取得方式', 600),
                                    'description': _text(item.get('description'), '画面制作要求', 1600)})
    shots = value.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 24:
        raise ValueError('口播稿应按自然表达安排1至24个完整段落。')
    cursor, used = 0, set()
    for number, item in enumerate(shots, 1):
        if not isinstance(item, dict):
            raise ValueError('视频镜头格式无效。')
        start = _seconds(item.get('start_seconds'), '镜头开始时间')
        end = _seconds(item.get('end_seconds'), '镜头结束时间')
        if start != cursor or end <= start or end > duration:
            raise ValueError('镜头时间应从0秒连续排列，不能重叠、留空或超过计划时长。')
        ids = item.get('material_ids')
        if (not isinstance(ids, list) or not ids or len(ids) > 6 or
                any(not isinstance(identifier, str) or identifier not in identifiers for identifier in ids)):
            raise ValueError('镜头引用了未列入清单的画面素材。')
        ids = list(dict.fromkeys(ids)); used.update(ids)
        result['shots'].append({'start_seconds': start, 'end_seconds': end, 'material_ids': ids,
                                **{key: _text(item.get(key), '镜头%d的%s' % (number, label), maximum)
                                   for key, label, maximum in [('voiceover', '口播', 900), ('visual', '画面', 1200),
                                                               ('onscreen_text', '屏幕文字', 500), ('editing', '剪辑安排', 800)]}})
        if with_prompts:
            result['shots'][-1].update({key: _text(item.get(key), '镜头%d的%s' % (number, label), 1800)
                                       for key, label in [('image_prompt', '生图提示词'), ('video_prompt', '生视频提示词')]})
        cursor = end
    if cursor != duration:
        raise ValueError('视频结尾必须纳入时间轴，全部镜头时长应等于计划时长。')
    if used != identifiers:
        raise ValueError('素材清单含未安排到镜头的图片，请明确用途后再生成。')
    publishing = value.get('publishing')
    if not isinstance(publishing, dict):
        raise ValueError('视频制作稿缺少封面和发布文字。')
    result['publishing'] = {'cover_text': _text(publishing.get('cover_text'), '封面文字', 100),
                            'caption': _text(publishing.get('caption'), '发布文案', 1000)}
    return result


def generation_prompts(production, shot):
    """Each copyable prompt carries its audience, design context and unmet dependencies."""
    context = '最终观众：%s。全片视觉风格：%s。画幅：%s。' % (
        production['audience'], production['visual_style'], production['aspect_ratio'])
    items = {item['id']: item for item in production['materials']}
    requirements = '；'.join('%s：%s；画面要求：%s' % (items[i]['name'], items[i]['source'], items[i]['description'])
                            for i in shot['material_ids'])
    references = '对应素材与参考要求（仍需提供或制作，不代表已有文件）：' + requirements + '。'
    typography = ('保留适合该画幅的字幕空位，不直接生成汉字、标题或书封文字，文字由剪辑时叠加。')
    image = context + '本镜头构图：' + shot['visual'] + '。' + shot['image_prompt'] + '。' + references + typography
    video = (context + '本镜头主体与构图：' + shot['visual'] + '。计划片段时长：%d秒。先取得本镜头已确认的静帧作为图生视频首帧；没有静帧时先按本镜头生图提示词制作并核对，'
             '不能仅凭名称生成需要准确形态的对象。' % (shot['end_seconds'] - shot['start_seconds']) +
             shot['video_prompt'] + '。保持参考对象的形态和结构，不凭空增加生长阶段或改变部位。' + references + typography)
    return {'image_prompt': image, 'video_prompt': video}


def render_body(production):
    """Canonical Markdown remains editable; older four-part packages remain valid."""
    lines = ['%s · 计划 %d 秒 · 画幅 %s' % (production['format'], production['duration_seconds'], production['aspect_ratio']),
             '', '时间为制作安排，录音或配音后按实际长度调整镜头。', '', '#### 配音稿', '']
    lines += [shot['voiceover'] + '\n' for shot in production['shots']]
    lines += ['#### 镜头脚本', '']
    names = {item['id']: item['name'] for item in production['materials']}
    for number, shot in enumerate(production['shots'], 1):
        lines += ['##### 镜头 %02d · %d–%d 秒' % (number, shot['start_seconds'], shot['end_seconds']), '',
                  '**画面：** ' + shot['visual'], '', '**屏幕文字：** ' + shot['onscreen_text'], '',
                  '**口播：** ' + shot['voiceover'], '', '**剪辑：** ' + shot['editing'], '',
                  '**使用素材：** ' + '、'.join(names[identifier] for identifier in shot['material_ids']), '']
    lines += ['#### 准备素材', '', '以下是待提供或制作的画面要求，尚未生成图片文件。', '']
    for number, item in enumerate(production['materials'], 1):
        lines += ['##### 素材 %02d · %s' % (number, item['name']), '',
                  '**取得方式：** ' + item['source'], '', '**画面要求：** ' + item['description'], '']
    lines += ['#### 发布文案', '', '**封面文字：** ' + production['publishing']['cover_text'], '',
              '**发布说明：** ' + production['publishing']['caption']]
    if production.get('visual_style'):
        lines += ['', '#### 生成提示词', '', '按镜头复制。先准备所列参考图并确认静帧，再制作动态片段；字幕在剪辑时添加。', '']
        for number, shot in enumerate(production['shots'], 1):
            prompts = generation_prompts(production, shot)
            lines += ['##### 镜头 %02d · %d–%d 秒' % (number, shot['start_seconds'], shot['end_seconds']), '',
                      '**生图提示词：** ' + prompts['image_prompt'], '',
                      '**生视频提示词：** ' + prompts['video_prompt'], '']
    return '\n'.join(lines).strip()


def shot_narration(source):
    """Read the editor's full narration field, including intentional line breaks."""
    starts = list(re.finditer(r'^\*\*口播：\*\*[ \t]*', source, re.M))
    if len(starts) != 1:
        raise ValueError('请保留每段唯一的口播栏目后再保存。')
    tail = source[starts[0].end():]
    end = re.search(r'^\*\*[^\n*]+：\*\*', tail, re.M)
    narration = tail[:end.start() if end else len(tail)].strip()
    if not narration:
        raise ValueError('口播内容不能为空。')
    return narration


def validate_manuscript(source):
    """Do not let an edited full package export two contradictory recording scripts."""
    names = ('配音稿', '镜头脚本', '准备素材', '发布文案')
    prompt_name = '生成提示词'
    found, offset, fence = [], 0, None
    for line in source.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif fence is None:
            heading = re.match(r'^####[ \t]+(.+?)\s*$', line)
            if heading and heading[1] in names + (prompt_name,):
                found.append((heading[1], offset, offset + len(line)))
        offset += len(line)
    if not set(names).issubset(item[0] for item in found):
        return False  # Old five-paragraph scripts and hand-written drafts remain readable.
    if tuple(item[0] for item in found) not in (names, names + (prompt_name,)):
        raise ValueError('视频制作稿的内容部分重复或顺序有误，请返回稿件整理后再下载。')
    voice = source[found[0][2]:found[1][1]].strip()
    timeline = source[found[1][2]:found[2][1]].strip()
    shots = re.split(r'^#####\s+镜头\s+', timeline, flags=re.M)[1:]
    spoken = []
    cursor = 0
    for shot in shots:
        time = re.match(r'\d+\s*[·｜|]\s*(\d+)\s*[–—-]\s*(\d+)\s*秒\s*\n', shot)
        narration = shot_narration(shot)
        if not time or int(time[1]) != cursor or int(time[2]) <= cursor:
            raise ValueError('镜头时段或口播格式已改变，请在镜头脚本中确认连续时段和逐镜口播。')
        cursor = int(time[2]); spoken.append(narration)
    compact = lambda value: re.sub(r'\s+', '', value)
    if not shots or compact(voice) != compact(''.join(spoken)):
        raise ValueError('配音稿与镜头口播不一致，请回到镜头脚本确认口播后保存。')
    planned = re.search(r'计划\s*(\d+)\s*秒', source[:found[0][1]])
    if planned and cursor != int(planned[1]):
        raise ValueError('镜头总时长与计划不一致，请确认最后镜头时间后再下载。')
    return True


INSTRUCTION = (
    '本阶段写供用户修改确认的完整口播正文，不是几句内容大纲，不生成生图或生视频提示词，也不生成任何图片视频文件。'
    '口播从开头引入、知识解释到自然结尾应连贯，可直接读出；镜头字段仅用于内部计划，不代表用户已经确认视觉方案。'
    '短视频channel_assets项必须增加video_production对象；其body和cta填写空字符串，系统会由结构生成正文，不能再额外追加口播。'
    'video_production格式严格为：{"format":"配图讲解","duration_seconds":60,"aspect_ratio":"9:16",'
    '"shots":[{"start_seconds":0,"end_seconds":6,"voiceover":"这一镜头实际念出的完整口播",'
    '"visual":"具体画面主体、景别、位置与动作","onscreen_text":"屏幕上实际显示的文字，不写制作说明",'
    '"editing":"如何切入、移动、标注或切出，写可执行安排","material_ids":["M01"]}],'
    '"materials":[{"id":"M01","name":"明确的素材名称","source":"到哪里取得，未提供的原书图片应写待提供；也可给制作替代方案",'
    '"description":"可复制给设计或配图制作人员的具体画面描述：视角、构图、局部、背景、所需准确特征、在视频中的用途"}],'
    '"publishing":{"cover_text":"短封面标题","caption":"可直接用于发布的视频说明"}}。'
    'material_ids是本次画面清单编号，不能冒充原书证据编号；原书依据仍在该channel_assets.asset_ids中给出。'
    'format未指定时用配图讲解，aspect_ratio未指定时用9:16；duration_seconds按用户要求，例如1分钟必须为60。'
    '最终观众就是project.brief.audience，按其理解能力和writing_notes的表达偏好安排口播、画面、信息密度和节奏。'
    '当前只输出上述口播稿字段，不要提前增加visual_style、image_prompt、video_prompt或生成提示词段落；用户确认口播稿并选择呈现方式后再单独生成提示词。'
    '本阶段writing_needs只列影响口播事实内容的具体缺项；尚未提供图片、封面、参考静帧或视频素材不是口播稿的写作缺项，禁止因此要求重新选材。'
    '视觉素材要求写入准备素材即可，后续提示词阶段再说明具体参考需求；不要在writing_needs重复提示缺图片。'
    '本阶段按口播自然段组织，不固定镜头数量，1至24段均可。兼容结构中的shots是口播段落，不是用户已确认的拍摄安排。'
    '计划时间从0秒到总时长连续排列，每段结束秒数等于下一段开始秒数；结尾内容也须纳入总时长，具体画面在确认口播后另行规划。'
    '每个镜头均给出可直接念的口播和实际屏幕文字；清单中每项画面均应安排到镜头，不能空列。'
    '口播长短服从实际配音时间，约1分钟先控制在约180至230个汉字，尺寸和数字要按读出后的长度考虑；不要让单个短镜头塞入整段知识。'
    '180至230个汉字仅作为60秒稿的编写参考，不是经过录音测量的语速或硬性字数配额。'
    '编写预算随总时长缩放，例如30秒先按约90至115汉字安排；这只是初稿容量参考，不为凑下限填字，也不能把60秒信息量压进30秒。长书名、数字读法和提问停顿都占时间，实际长度须录音后核准。'
    '面向少年或入门观众，关键术语首次出现先用直观话解释，再按需给术语名；非核心分类、尺寸、年代列表直接省略，不连续堆多个未解释术语。专业观众可保留所需术语，但仍服从本次具体理解目标。'
    '30秒内容聚焦一个小问题和少量必要事实；可以用两个简短例子做明确对照，不同时展开形态、尺寸、生境、俗名等多条知识线。'
    '开场只提出钩子或问题，不先完整复述后面马上讲述的故事；结尾给出一个简短观察或阅读动作，不再重复全文。'
    '每个计划时段安排有意义的完整表达，避免几个字占据一大段时间造成无意长留白；如需停顿，应服务于理解而不是填满时间。'
    '不要为达到字数而堆数字、重复说法或无关知识，优先解释清楚一个问题，并让各段听起来前后相接。'
    '制作信息需足够具体，不要只重复“找图、加字幕、配音乐”，不要靠加长口播或重复分析凑字数。'
    '一条1分钟视频集中讲一个问题、优先1至2个相互关联的对象，不必使用所有已选素材。'
    '本次材料是文字和出处，未提供真实图片文件；不能宣称已有可直接使用的书图、封面或视频。'
    '主要画面应呈现正在讲述的对象或行动，不能因为参考图尚未提供就把全片退化为文字卡。'
    '需要原书图片、实拍或准确对象参考图时，在source和提示词明确先提供什么视角或部位的图、保留哪些形态；以取得参考图后的主体镜头为主要方案，文字卡或环境示意仅作为可选替代。'
    '科普图像区分准确对象形态与示意；缺少参考时不能让AI凭名称猜测具体结构，也不能用虚构画面证明过程。'
    '涉及名称、俗名或历史称谓时，仅陈述来源支持的称谓；没有明确说明时不推断命名原因，不为凑篇幅专设俗名段。'
    '每个数字必须准确对应来源中的对象或部位，不能将相近或等长改写成相同尺寸范围；删除对本次核心问题没有帮助的参数，口播优先用可观察的差别。'
    '自然科学题材不补写没有依据的季节、发育阶段、功能或生存机制；人物历史题材不补写人物动机、年代或经历；文学虚构情节不转述为真实史实；社科观点不扩展成未经提供的数据或案例。'
    '标题同样遵守来源支持范围，不扩大因果结论。'
    '植物科普中，来源只说明生长位置时，标题与口播只表达长在哪里，不得推断根系、基质或养分来源；禁止据此写“不需要土”“没有把根扎进土里”等结论。'
    '每个镜头画面必须出现当镜口播所指向的对象或具体动作；口播让观众看对象时，不能只安排空环境或一张无关文字卡。'
    '上述事实约束在生成时执行，不要向观众复述规则、解释证据边界或补写与核心问题无关的澄清。'
    '口播只讲观众需要听到的具体内容；不要用“这只是俗名、不代表某个结论”等话把内部写作约束说给观众。'
    '配音稿与屏幕字幕面向观众；素材和剪辑字段面向制作人员。所有字段用具体内容，内部策划判断仍留在其他字段。'
)

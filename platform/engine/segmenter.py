# -*- coding: utf-8 -*-
"""无标点古籍的自动断句。

为什么必须有这一步：
  Kanripo 等高质量古籍底本大多是**白文无标点**（原文如此，不是抽取丢失）。
  未断句时全书找不到一个句号，`savg` 等于汉字数（如《逸周书》19556 字/句），
  会被 gate 正确但无用武之地地判成「句读缺失」，于是古代典籍整类无法测。

  这不是「换个底本」能解决的 —— 带标点的排印本往往版权受限。
  所以只能在系统内补断句。

口径（必须如实告知用户）：
  1. 这里补的是**算法句读，不是原文标点，也不是校勘成果**。
  2. 只用于测量与切段，**不得写入任何引文产物**。
     知识点卡的「原文」字段必须仍是白文，否则等于伪造底本。
  3. 断句质量只要求「句长分布合理」，不追求训读正确。

规则来源：文言句读的常见落点是句末语气词与固定结构。
  语气词：也 矣 焉 乎 哉 耶 與 歟 夫 兮 耳 爾
  固定结构：……者，……也 / 不亦……乎 / 何其……也
"""
import re

# 句末语气词：这些字之后大概率断句
END = '也矣焉乎哉耶與歟兮耳爾已夫'
# 强断点：几乎一定是句末
STRONG = '也矣焉哉乎耶歟兮'
# 句首词：这些词之前必断（承上启下）
HEAD = ('凡', '故', '是以', '是故', '然則', '然则', '若夫', '今夫', '且夫',
        '雖然', '虽然', '於是', '于是', '及至', '至若', '若乃', '乃若',
        '孔子曰', '孟子曰', '詩云', '诗云', '書曰', '书曰', '傳曰', '传曰')
# 永不作为句末的组合（避免把「也」在词中切断）
NO_END = ('也先', '也里', '也速', '者流', '焉知', '焉得', '乎哉')


def _is_han(ch):
    return '\u3400' <= ch <= '\u4dbf' or '\u4e00' <= ch <= '\u9fff' \
        or '\uf900' <= ch <= '\ufaff' or '\U00020000' <= ch <= '\U0002fa1f'


def punctuate(text, maxlen=42, minlen=4):
    """给白文补句读。返回带标点的文本。

    maxlen：单句上限。超过则找最近的逗号候选点（之/而/以/则/其/所）断开。
    """
    out = []
    for para in re.split(r'\n+', text):
        p = re.sub(r'\s+', '', para)
        if not p:
            out.append('')
            continue
        buf = ''
        for i, ch in enumerate(p):
            buf += ch
            nxt = p[i + 1] if i + 1 < len(p) else ''
            # 1) 句首词前断（当前字是句首词的起点，且 buf 已够长）
            if len(buf) >= minlen and nxt:
                hit = False
                for h in HEAD:
                    if p.startswith(h, i + 1) and len(buf) >= minlen:
                        hit = True
                        break
                if hit and buf[-1] not in '，、；：':
                    buf += '。'
                    out.append(buf)
                    buf = ''
                    continue
            # 2) 强语气词后断
            if ch in STRONG and len(buf) >= minlen:
                if not any(buf.endswith(x) for x in NO_END):
                    if nxt and not _is_han(nxt):
                        pass
                    buf += '。'
                    out.append(buf)
                    buf = ''
                    continue
            # 3) 超长句在虚词处补逗号
            if len(buf) >= maxlen:
                for k in range(len(buf) - 1, max(minlen, len(buf) - 14), -1):
                    if buf[k] in '之而以則其所以與于於':
                        out.append(buf[:k + 1] + '，')
                        buf = buf[k + 1:]
                        break
        if buf.strip():
            out.append(buf + '。')
        out.append('')
    return '\n'.join(out)


def has_punct(text, thresh=0.0008):
    """判断文本是否已有句读。返回 (有无标点, 句号密度)。
    古汉语正常断句约每 15~40 字一个句号，即 25~65 个/千字。
    密度低于 thresh（0.8/千）视为无标点白文。"""
    h = sum(1 for c in text if _is_han(c))
    n = len(re.findall(r'[。！？]', text))
    if h == 0:
        return True, 0
    r = n * 1000.0 / h
    return r >= thresh, round(r, 2)
# -*- coding: utf-8 -*-
"""跨平台路径解析。

原来所有模块里写死 `D:/workbuddy/图书蒸馏/...`，换机器就跑不了。
项目根 = platform/engine 的上两级，允许用环境变量 BOOKDISTILL_ROOT 覆盖。
"""
import os

ENGINE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(ENGINE)
ROOT = os.environ.get('BOOKDISTILL_ROOT') or os.path.dirname(PLATFORM)

RAW = os.path.join(ROOT, '书库分类', 'raw')
OUT = os.path.join(PLATFORM, 'out')
CARDS = os.path.join(PLATFORM, 'cards')
LIB = os.path.join(PLATFORM, 'library')
HTML_BOARD = os.path.join(PLATFORM, '书库平台看板.html')
HTML_TAGDB = os.path.join(PLATFORM, '图书标签数据库.html')
HTML_CARDS = os.path.join(PLATFORM, '候选卡资产库.html')

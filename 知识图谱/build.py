# -*- coding: utf-8 -*-
"""把 kg_data.json 内联进原型模板，产出单文件可点击原型。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
tpl = open(os.path.join(HERE, '_proto_template.html'), encoding='utf-8').read()
data = open(os.path.join(HERE, 'kg_data.json'), encoding='utf-8').read()
out = os.path.join(HERE, '知识图谱_原型_孙子兵法.html')
open(out, 'w', encoding='utf-8').write(tpl.replace('__KG_DATA__', data))
print('built', out, len(open(out, encoding='utf-8').read()) // 1024, 'KB')

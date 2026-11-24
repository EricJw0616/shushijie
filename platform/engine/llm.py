# -*- coding: utf-8 -*-
"""最小的模型调用层：OpenAI 兼容 /chat/completions，无第三方依赖。

配置优先级：环境变量 > app/.env
  BOOKDISTILL_LLM_BASE   例 https://dashscope.aliyuncs.com/compatible-mode/v1
  BOOKDISTILL_LLM_KEY
  BOOKDISTILL_LLM_MODEL

只做三件事：发请求、超时重试、返回文本与用量。业务逻辑不放这里。
"""
import json
import os
import time
import urllib.error
import urllib.request

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         'app', '.env')


def _load_env():
    cfg = {}
    try:
        with open(_ENV_PATH, encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    cfg[k.strip()] = v.strip()
    except Exception:
        pass
    for k in ('BOOKDISTILL_LLM_BASE', 'BOOKDISTILL_LLM_KEY', 'BOOKDISTILL_LLM_MODEL',
              'BOOKDISTILL_XHS_VISION_MODEL'):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    base = cfg.get('BOOKDISTILL_LLM_BASE') or ''
    if base.startswith('https://dashscope.aliyuncs.com/'):
        cfg.setdefault('BOOKDISTILL_XHS_VISION_MODEL', 'qwen3.8-flash')
    return cfg


CFG = _load_env()


def ready():
    return bool(CFG.get('BOOKDISTILL_LLM_BASE') and CFG.get('BOOKDISTILL_LLM_KEY')
                and CFG.get('BOOKDISTILL_LLM_MODEL'))


class SourceRefusedError(RuntimeError):
    pass


def chat(messages, max_tokens=2000, temperature=0, thinking=False, timeout=120, retries=2, json_mode=False, model=None):
    """返回 {'text','usage','model'}；失败抛 RuntimeError。"""
    if not ready():
        raise RuntimeError('模型未配置（缺 BASE/KEY/MODEL）')
    url = CFG['BOOKDISTILL_LLM_BASE'].rstrip('/') + '/chat/completions'
    selected_model = model or CFG['BOOKDISTILL_LLM_MODEL']
    body = {
        'model': selected_model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }
    if not thinking:
        body['enable_thinking'] = False      # 判定类任务不需要思考链，省钱也省时
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + CFG['BOOKDISTILL_LLM_KEY'],
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            msg = d['choices'][0]['message']
            return {'text': (msg.get('content') or '').strip(),
                    'usage': d.get('usage') or {},
                    'model': d.get('model') or selected_model}
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', 'replace')[:300]
            except Exception:
                pass
            if e.code == 400 and 'data_inspection_failed' in detail:
                raise SourceRefusedError('模型未接受这部分原文。') from None
            last = 'HTTP %s %s' % (e.code, detail)
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:
            last = '%s: %s' % (type(e).__name__, e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError('模型调用失败：%s' % last)

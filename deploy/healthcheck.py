"""Check the local HTTP service without an external call or a model request."""
import base64
import json
import os
import urllib.request

headers = {}
user, password = os.environ.get('BOOKDISTILL_USER'), os.environ.get('BOOKDISTILL_PASS')
if user and password:
    encoded = base64.b64encode((user + ':' + password).encode()).decode()
    headers['Authorization'] = 'Basic ' + encoded
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
request = urllib.request.Request('http://127.0.0.1:8943/api/version', headers=headers)
with opener.open(request, timeout=3) as response:
    data = json.load(response)
    if response.status != 200 or not data.get('version'):
        raise SystemExit(1)

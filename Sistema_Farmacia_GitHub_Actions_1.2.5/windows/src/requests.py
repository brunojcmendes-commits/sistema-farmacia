"""Pequeno adaptador HTTP offline usando apenas a biblioteca padrão.
Compatível com as operações usadas pelo sistema.
"""
import json, urllib.request, urllib.parse, urllib.error
AUTH_TOKEN=''
def set_bearer_token(token):
    global AUTH_TOKEN
    AUTH_TOKEN=token or ''
class RequestException(Exception): pass
class _Exceptions: RequestException=RequestException
exceptions=_Exceptions()
class Response:
    def __init__(self, status, data): self.status_code=status; self._data=data
    def json(self): return json.loads(self._data.decode('utf-8'))
def _call(method,url,params=None,json_data=None,timeout=5):
    try:
        if params:
            sep='&' if '?' in url else '?'; url += sep + urllib.parse.urlencode(params)
        data=None; headers={'Accept':'application/json'}
        if AUTH_TOKEN: headers['Authorization']='Bearer '+AUTH_TOKEN
        if json_data is not None:
            data=json.dumps(json_data,ensure_ascii=False).encode('utf-8'); headers['Content-Type']='application/json'
        req=urllib.request.Request(url,data=data,headers=headers,method=method)
        with urllib.request.urlopen(req,timeout=timeout) as r: return Response(r.status,r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code,e.read())
    except Exception as e: raise RequestException(str(e)) from e
def get(url,params=None,timeout=5): return _call('GET',url,params=params,timeout=timeout)
def post(url,params=None,json=None,timeout=5): return _call('POST',url,params=params,json_data=json,timeout=timeout)
def put(url,params=None,json=None,timeout=5): return _call('PUT',url,params=params,json_data=json,timeout=timeout)
def delete(url,params=None,json=None,timeout=5): return _call('DELETE',url,params=params,json_data=json,timeout=timeout)

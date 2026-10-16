import http.client
import json
from urllib.parse import urlsplit


def request(url, method="GET", body=None, headers=None, timeout=3):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("expected http(s) URL without credentials or fragment")
    cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    connection = cls(parts.hostname, parts.port, timeout=timeout)
    try:
        connection.request(method, (parts.path or "/") + ("?"+parts.query if parts.query else ""), body, headers or {})
        response = connection.getresponse()
        data = response.read(1024*1024+1)
        if len(data)>1024*1024:
            raise ValueError("response too large")
        return response.status, dict(response.getheaders()), data
    finally:
        connection.close()


def json_request(url, method="GET", value=None, timeout=3):
    body = json.dumps(value, allow_nan=False).encode() if value is not None else None
    status, headers, data = request(url, method, body, {"Content-Type":"application/json"},timeout)
    return status, json.loads(data)

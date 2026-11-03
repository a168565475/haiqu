"""仅连接专属运行进程；外部消息在此收敛为白名单，不返回原始 RPC。"""
import json
import math
import socket
import struct
import time
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from django.views.decorators.debug import sensitive_variables


MAX_FRAME = 16 * 1024 * 1024
RUNTIME_ERRORS = frozenset({
    'INVALID_REQUEST', 'BUSY', 'NOT_FOUND', 'NOT_READY', 'UPSTREAM_UNAVAILABLE',
    'AUTH_REQUIRED', 'MODEL_UNAVAILABLE', 'USAGE_LIMIT_EXCEEDED', 'TIMEOUT', 'INTERRUPTED',
})
ACTIONS = ('login', 'switch', 'disconnect', 'refresh', 'test', 'discover', 'extract')


class RuntimeFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def invalid():
    raise RuntimeFailure('INVALID_RESPONSE')


def text(value, maximum=200, *, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        invalid()
    if any(ord(char) < 32 for char in value):
        invalid()
    return value


def timestamp(value):
    if value is None:
        return None
    value = text(value, 64, empty=False)
    try:
        parsed = parse_datetime(value)
    except ValueError:
        invalid()
    if parsed is None or not is_aware(parsed):
        invalid()
    return value


def identifier(value):
    try:
        return str(UUID(text(value, 36, empty=False)))
    except ValueError:
        invalid()


def integer(value, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        invalid()
    return value


def mapping(value, required):
    if not isinstance(value, dict) or not set(required).issubset(value):
        invalid()
    return value


def clean_operation(value):
    if value is None:
        return None
    mapping(value, ('id', 'generation', 'action', 'state', 'error_code', 'completed_at'))
    if value['action'] not in ACTIONS or value['state'] not in ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED'):
        invalid()
    code = value['error_code']
    if not isinstance(code, str) or (code != '' and code not in RUNTIME_ERRORS):
        invalid()
    return {'id': identifier(value['id']), 'generation': integer(value['generation']),
            'action': value['action'], 'state': value['state'], 'error_code': code,
            'completed_at': timestamp(value['completed_at'])}


def clean_limits(value):
    if value is None:
        return None
    mapping(value, ('windows', 'credits'))
    if not isinstance(value['windows'], list) or len(value['windows']) > 20:
        invalid()
    windows = []
    for window in value['windows']:
        mapping(window, ('name', 'used_percent', 'window_minutes', 'resets_at'))
        used = window['used_percent']
        if used is not None and (isinstance(used, bool) or not isinstance(used, (int, float))
                                 or used < 0 or used > 1000000 or not math.isfinite(used)):
            invalid()
        minutes = window['window_minutes']
        if minutes is not None:
            integer(minutes, 0)
        windows.append({'name': text(window['name'], 100), 'used_percent': used,
                        'window_minutes': minutes, 'resets_at': timestamp(window['resets_at'])})
    credits = value['credits']
    if credits is not None:
        mapping(credits, ('unlimited', 'has_credits', 'balance'))
        if not isinstance(credits['unlimited'], bool) or not isinstance(credits['has_credits'], bool):
            invalid()
        balance = credits['balance']
        if balance is not None:
            balance = text(balance, 100)
        credits = {'unlimited': credits['unlimited'], 'has_credits': credits['has_credits'], 'balance': balance}
    return {'windows': windows, 'credits': credits}


@sensitive_variables()
def clean_snapshot(value):
    mapping(value, ('boot_id', 'cli_version', 'account', 'models', 'rate_limits', 'limits_updated_at', 'operation'))
    account = value['account']
    if account is not None:
        mapping(account, ('display_name', 'plan_type'))
        account = {'display_name': text(account['display_name']), 'plan_type': text(account['plan_type'], 64)}
    if not isinstance(value['models'], list) or len(value['models']) > 200:
        invalid()
    models = []
    for model in value['models']:
        mapping(model, ('id', 'display_name'))
        models.append({'id': text(model['id'], 200, empty=False), 'display_name': text(model['display_name'])})
    if len({model['id'] for model in models}) != len(models):
        invalid()
    return {'boot_id': identifier(value['boot_id']), 'cli_version': text(value['cli_version'], 64),
            'account': account, 'models': models, 'rate_limits': clean_limits(value['rate_limits']),
            'limits_updated_at': timestamp(value['limits_updated_at']), 'operation': clean_operation(value['operation'])}


@sensitive_variables()
def clean_challenge(value):
    mapping(value, ('operation_id', 'verification_url', 'user_code', 'expires_at'))
    url = text(value['verification_url'], 500, empty=False)
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname == 'auth.openai.com'
                 and not parsed.username and not parsed.password and parsed.port is None
                 and not parsed.query and not parsed.fragment and '\\' not in url)
    except ValueError:
        invalid()
    if not valid:
        invalid()
    code = text(value['user_code'], 64, empty=False)
    if not all(char.isascii() and (char.isalnum() or char == '-') for char in code):
        invalid()
    expiry = timestamp(value['expires_at'])
    if expiry is None:
        invalid()
    return {'operation_id': identifier(value['operation_id']), 'verification_url': url,
            'user_code': code, 'expires_at': expiry}


class RuntimeClient:
    def __init__(self):
        self.path = getattr(settings, 'CODEX_RUNTIME_SOCKET', '/run/haiqu-codex/runtime.sock')

    @staticmethod
    def _receive(sock, size, deadline):
        chunks = []
        remaining = size
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise RuntimeFailure('UPSTREAM_UNAVAILABLE')
            sock.settimeout(timeout)
            chunk = sock.recv(remaining)
            if not chunk:
                raise RuntimeFailure('UPSTREAM_UNAVAILABLE')
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    @sensitive_variables()
    def call(self, method, params):
        if method not in ('status', 'start', 'operation', 'cancel', 'challenge', 'result'):
            raise RuntimeFailure('INVALID_REQUEST')
        request = json.dumps({'method': method, 'params': params}, separators=(',', ':'), allow_nan=False).encode()
        if len(request) > MAX_FRAME:
            raise RuntimeFailure('INVALID_REQUEST')
        try:
            deadline = time.monotonic() + 5
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect(self.path)
                sock.sendall(struct.pack('!I', len(request)) + request)
                length = struct.unpack('!I', self._receive(sock, 4, deadline))[0]
                # 状态/账号响应仍维持原 256 KiB 上限，只有解析结果可携带较大正文。
                response_limit = MAX_FRAME if method == 'result' else 256 * 1024
                if not 0 < length <= response_limit:
                    invalid()
                response = json.loads(self._receive(sock, length, deadline))
        except (OSError, TimeoutError):
            raise RuntimeFailure('UPSTREAM_UNAVAILABLE') from None
        except (UnicodeError, ValueError, struct.error):
            raise RuntimeFailure('INVALID_RESPONSE') from None
        mapping(response, ('ok',))
        if response['ok'] is False:
            code = response.get('error', {}).get('code') if isinstance(response.get('error'), dict) else None
            raise RuntimeFailure(code if isinstance(code, str) and code in RUNTIME_ERRORS else 'INVALID_RESPONSE')
        if response['ok'] is not True or 'data' not in response:
            invalid()
        data = response['data']
        if method == 'result':
            mapping(data, ('boot_id', 'operation_id', 'generation', 'result'))
            if (identifier(data['operation_id']) != params.get('operation_id')
                    or integer(data['generation']) != params.get('generation')
                    or not isinstance(data['result'], dict)
                    or len(json.dumps(data['result'], ensure_ascii=False).encode()) > 2 * 1024 * 1024):
                invalid()
            return {'boot_id': identifier(data['boot_id']), 'result': data['result']}
        if method == 'challenge':
            result = clean_challenge(data)
            if result['operation_id'] != params.get('operation_id'):
                invalid()
            return result
        if method == 'operation':
            mapping(data, ('boot_id', 'operation', 'snapshot'))
            snapshot = clean_snapshot(data['snapshot'])
            boot_id = identifier(data['boot_id'])
            operation = clean_operation(data['operation'])
            if boot_id != snapshot['boot_id']:
                invalid()
            if operation and (operation['id'] != params.get('operation_id') or operation['generation'] != params.get('generation')):
                invalid()
            return {'boot_id': boot_id, 'operation': operation, 'snapshot': snapshot}
        return clean_snapshot(data)

"""一个账号、一个活动操作；设备码与原始 RPC 只保存在内存。"""
import asyncio
from collections import OrderedDict
import copy
from datetime import datetime, timedelta, timezone
import json
import re
import sys
from urllib.parse import urlsplit
import uuid

from .protocol import AppServerSession, RuntimeErrorCode, TOOL_TYPES, report_error, require, strict_json


MODEL_PATTERN = re.compile(r'[A-Za-z0-9._:/-]{1,160}')
PLAN_TYPES = {'free', 'go', 'plus', 'pro', 'prolite', 'promax', 'team', 'self_serve_business_prolite',
              'self_serve_business_usage_based', 'business', 'ent26', 'enterprise_cbp_automation',
              'enterprise_cbp_usage_based', 'enterprise', 'edu', 'edu_plus', 'edu_pro', 'sci', 'sci_plus', 'unknown'}
TEST_PROMPT = 'Return exactly the JSON object {"ok":true}. Do not call tools.'
TURN_STATUSES = {'completed', 'interrupted', 'failed', 'inProgress'}
CODEX_ERROR_NAMES = {'contextWindowExceeded', 'sessionBudgetExceeded', 'usageLimitExceeded', 'rateLimitExceeded',
                    'flexUnavailable', 'serverOverloaded', 'modelNotFound', 'cyberPolicy',
                    'misalignmentPolicyViolation', 'tooManyDenials', 'internalServerError', 'unauthorized',
                    'badRequest', 'threadRollbackFailed', 'sandboxError', 'other'}
CODEX_ERROR_VARIANTS = {'httpConnectionFailed', 'responseStreamConnectionFailed', 'responseStreamDisconnected',
                       'responseTooManyFailedAttempts', 'activeTurnNotSteerable'}


class SnapshotLimitError(RuntimeErrorCode):
    def __init__(self):
        super().__init__('UPSTREAM_UNAVAILABLE')


def now():
    return datetime.now(timezone.utc).isoformat()


def report_primary_failure(operation, error_code):
    print(json.dumps({'event': 'operation_failure', 'action': operation.params['action'],
                      'stage': operation.stage, 'error_code': error_code}), file=sys.stderr, flush=True)


def turn_error_summary(error):
    """只保留固定协议分类；开放字符串、正文和未知对象绝不成为诊断字段。"""
    category, http_status = None, None
    if error is not None:
        if type(error) is not dict:
            return {'codex_error_info': 'UNKNOWN', 'http_status': None}
        info = error.get('codexErrorInfo')
        if info is None:
            category = None
        elif type(info) is str and info in CODEX_ERROR_NAMES:
            category = info
        elif type(info) is dict and len(info) == 1:
            variant = next(iter(info))
            details = info[variant]
            if variant in CODEX_ERROR_VARIANTS and type(details) is dict:
                category = variant
                status = details.get('httpStatusCode')
                if variant != 'activeTurnNotSteerable' and type(status) is int and 100 <= status <= 599:
                    http_status = status
            else:
                category = 'UNKNOWN'
        else:
            category = 'UNKNOWN'
    return {'codex_error_info': category, 'http_status': http_status}


def account_summary(account):
    if account is None:
        return None
    require(type(account) is dict and account.get('type') == 'chatgpt', 'AUTH_REQUIRED')
    email = account.get('email')
    match = re.fullmatch(r'([^@\s]{1,64})@([A-Za-z0-9.-]{1,253})', email) if type(email) is str else None
    require(match is not None)
    local, domain = match.groups()
    parts = domain.split('.')
    require(all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in parts)
            and all(ord(c) >= 32 for c in local))
    initial = local[0] if local[0].isalnum() else '*'
    suffix = '.' + parts[-1].lower() if len(parts) > 1 else ''
    display_name = f'{initial}***@{domain[0].lower()}***{suffix}'
    plan = account.get('planType')
    return {'display_name': display_name, 'plan_type': plan if type(plan) is str and plan in PLAN_TYPES else 'unknown'}


def normalize_limits(result):
    require(type(result) is dict and type(result.get('rateLimits')) is dict)
    primary = result['rateLimits']
    buckets = result.get('rateLimitsByLimitId')
    if buckets is None:
        buckets = {'codex': primary}
    require(type(buckets) is dict and len(buckets) <= 32)
    windows = []
    for name, bucket in buckets.items():
        require(type(name) is str and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,80}', name) and type(bucket) is dict)
        for period in ('primary', 'secondary'):
            window = bucket.get(period)
            if window is None:
                continue
            require(type(window) is dict)
            used, minutes, reset = (window.get(key) for key in ('usedPercent', 'windowDurationMins', 'resetsAt'))
            require(type(used) is int and 0 <= used <= 1000000)
            require(minutes is None or type(minutes) is int and 0 <= minutes <= 5256000)
            require(reset is None or type(reset) is int and 0 <= reset <= 253402300799)
            reset_time = datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset is not None else None
            windows.append({'name': f'{name}:{period}', 'used_percent': used,
                            'window_minutes': minutes, 'resets_at': reset_time})
            if len(windows) > 20:
                raise SnapshotLimitError()
    credits = primary.get('credits')
    if credits is not None:
        require(type(credits) is dict and type(credits.get('unlimited')) is bool and type(credits.get('hasCredits')) is bool)
        balance = credits.get('balance')
        require(balance is None or type(balance) is str and re.fullmatch(r'\d{1,18}(?:\.\d{1,12})?', balance))
        credits = {'unlimited': credits['unlimited'], 'has_credits': credits['hasCredits'], 'balance': balance}
    return {'windows': windows, 'credits': credits}


class Operation:
    def __init__(self, params):
        import hashlib
        self.params_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        self.params = copy.deepcopy(params)
        self.public = {'id': params['operation_id'], 'generation': params['generation'], 'action': params['action'],
                       'state': 'RUNNING', 'error_code': '', 'completed_at': None}
        self.task = self.session = self.login_id = self.turn = self.challenge = None
        self.started = self.cancel_requested = self.cleaning = False
        self.cleanup_failed = False
        self.stage = 'operation_start'
        self.result = None


class Runtime:
    def __init__(self, session_factory=AppServerSession, login_timeout=900, operation_timeout=900,
                 login_completion_grace=120):
        self.session_factory = session_factory
        self.login_timeout, self.operation_timeout = login_timeout, operation_timeout
        self.login_completion_grace = login_completion_grace
        self.boot_id = str(uuid.uuid4())
        self.account = self.rate_limits = self.limits_updated_at = None
        self.models = []
        self.operations = OrderedDict()
        self.active = None
        self.generation = 0
        self.unavailable = self.closing = False

    def snapshot(self):
        latest = next(reversed(self.operations.values()), None) if self.operations else None
        return copy.deepcopy({'boot_id': self.boot_id, 'cli_version': '0.165.0', 'account': self.account,
                              'models': self.models, 'rate_limits': self.rate_limits,
                              'limits_updated_at': self.limits_updated_at,
                              'operation': latest.public if latest else None})

    def lookup(self, params):
        require(type(params) is dict and set(params) == {'operation_id', 'generation'}, 'INVALID_REQUEST')
        self.validate_identity(params)
        operation = self.operations.get(params['operation_id'])
        require(operation is not None and operation.public['generation'] == params['generation'], 'NOT_FOUND')
        return operation

    @staticmethod
    def validate_identity(params):
        try:
            require(type(params.get('operation_id')) is str
                    and str(uuid.UUID(params['operation_id'])) == params['operation_id'], 'INVALID_REQUEST')
        except (ValueError, AttributeError):
            raise RuntimeErrorCode('INVALID_REQUEST') from None
        require(type(params.get('generation')) is int and 1 <= params['generation'] <= 2**63 - 1, 'INVALID_REQUEST')

    async def dispatch(self, method, params):
        require(type(method) is str and type(params) is dict, 'INVALID_REQUEST')
        if method == 'status':
            require(not params, 'INVALID_REQUEST')
            return self.snapshot()
        if method == 'start':
            parsing = params.get('action') in ('discover', 'extract')
            require(set(params) == ({'operation_id', 'generation', 'action', 'model', 'payload'} if parsing
                                   else {'operation_id', 'generation', 'action', 'model'}), 'INVALID_REQUEST')
            self.validate_identity(params)
            require(type(params['action']) is str and params['action'] in {'login', 'switch', 'disconnect', 'refresh', 'test', 'discover', 'extract'}
                    and type(params['model']) is str and len(params['model']) <= 160, 'INVALID_REQUEST')
            require(not params['model'] or MODEL_PATTERN.fullmatch(params['model']), 'INVALID_REQUEST')
            require(params['action'] not in ('test', 'discover', 'extract') or params['model'], 'INVALID_REQUEST')
            if parsing:
                from .parsing import validate_payload
                validate_payload(params['payload'])
            existing = self.operations.get(params['operation_id'])
            if existing:
                import hashlib
                require(existing.params_hash == hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest(), 'INVALID_REQUEST')
                snapshot = self.snapshot()
                snapshot['operation'] = copy.deepcopy(existing.public)
                return snapshot
            require(not self.closing and not self.unavailable and len(self.operations) < 4096, 'NOT_READY')
            require(self.active is None, 'BUSY')
            # 只有上一操作落库并释放互斥后才能启动下一操作；不长期缓存业务原文。
            for previous in self.operations.values():
                previous.result = None
                previous.params.pop('payload', None)
            require(params['generation'] >= self.generation, 'NOT_READY')
            self.generation = params['generation']
            operation = Operation(params)
            self.operations[params['operation_id']] = operation
            self.active = operation
            operation.task = asyncio.create_task(self._execute(operation))
            return self.snapshot()
        if method not in {'operation', 'cancel', 'challenge', 'result'}:
            raise RuntimeErrorCode('INVALID_REQUEST')
        if method == 'operation':
            require(set(params) == {'operation_id', 'generation'}, 'INVALID_REQUEST')
            self.validate_identity(params)
            if params['operation_id'] not in self.operations:
                return {'boot_id': self.boot_id, 'operation': None, 'snapshot': self.snapshot()}
        operation = self.lookup(params)
        if method == 'result':
            require(operation.public['state'] == 'SUCCEEDED' and operation.result is not None, 'NOT_FOUND')
            return {'boot_id': self.boot_id, 'operation_id': operation.public['id'],
                    'generation': operation.public['generation'], 'result': copy.deepcopy(operation.result)}
        if method == 'operation':
            return {'boot_id': self.boot_id, 'operation': copy.deepcopy(operation.public), 'snapshot': self.snapshot()}
        if method == 'cancel':
            if operation.public['state'] == 'RUNNING' and not operation.cancel_requested:
                operation.cancel_requested = True
                operation.challenge = None
                if operation.started and not operation.cleaning:
                    operation.task.cancel()
            return self.snapshot()
        require(operation.public['state'] == 'RUNNING' and not operation.cancel_requested, 'NOT_FOUND')
        require(operation.challenge is not None, 'NOT_READY')
        require(datetime.fromisoformat(operation.challenge['expires_at']) > datetime.now(timezone.utc), 'NOT_FOUND')
        return copy.deepcopy(operation.challenge)

    def current(self, operation):
        require(self.active is operation and operation.public['generation'] == self.generation, 'INTERRUPTED')

    async def open_session(self, operation):
        self.current(operation)
        operation.stage = 'session_start'
        operation.session = self.session_factory()
        await operation.session.start()
        return operation.session

    async def close_session(self, operation):
        if operation.session is not None:
            operation.stage = 'session_close'
            session = operation.session
            await session.close()
            operation.session = None

    async def read_account(self, operation, refresh=False):
        operation.stage = 'account_read'
        response = await operation.session.request('account/read', {'refreshToken': refresh}, timeout=60 if refresh else 20)
        self.current(operation)
        require(type(response) is dict and 'account' in response)
        self.account = account_summary(response['account'])
        # 新账号读取后不能让上一次账号/额度快照继续伪装成本轮已刷新。
        self.models, self.rate_limits, self.limits_updated_at = [], None, None
        return self.account

    async def refresh(self, operation):
        require(await self.read_account(operation, refresh=True) is not None, 'AUTH_REQUIRED')
        models, cursor, seen = [], None, set()
        for _ in range(20):
            operation.stage = 'model_list'
            params = {'includeHidden': False, 'limit': 100}
            if cursor:
                params['cursor'] = cursor
            response = await operation.session.request('model/list', params)
            require(type(response.get('data')) is list)
            for model in response['data']:
                require(type(model) is dict)
                if model.get('hidden') is True:
                    continue
                identifier, name = model.get('model'), model.get('displayName')
                require(type(identifier) is str and MODEL_PATTERN.fullmatch(identifier))
                require(type(name) is str and 0 < len(name) <= 160 and not any(ord(c) < 32 for c in name))
                models.append({'id': identifier, 'display_name': name})
            cursor = response.get('nextCursor')
            if cursor is None:
                break
            require(type(cursor) is str and 0 < len(cursor) <= 512 and cursor not in seen)
            seen.add(cursor)
        else:
            raise RuntimeErrorCode('UPSTREAM_UNAVAILABLE')
        require(len({m['id'] for m in models}) == len(models) and len(models) <= 200)
        require(len(json.dumps(models, ensure_ascii=False).encode()) <= 128 * 1024)
        self.current(operation)
        self.models = models
        operation.stage = 'rate_limits'
        try:
            limits = normalize_limits(await operation.session.request('account/rateLimits/read', {}))
        except SnapshotLimitError:
            raise
        except Exception as error:
            # 账号和可见模型已独立确认；额度未知不伪造为0，也不阻断登录/模型测试。
            self.rate_limits, self.limits_updated_at = None, None
            report_error('rate_limits_unavailable', error)
        else:
            self.current(operation)
            self.rate_limits, self.limits_updated_at = limits, now()

    async def login(self, operation):
        if await self.read_account(operation) is not None:
            await self.refresh(operation)
            return
        operation.stage = 'login_start'
        response = await operation.session.request('account/login/start', {'type': 'chatgptDeviceCode'}, timeout=60)
        operation.stage = 'login_challenge'
        identifier = response.get('loginId')
        try:
            require(type(identifier) is str and str(uuid.UUID(identifier)) == identifier)
        except (ValueError, AttributeError):
            raise RuntimeErrorCode('UPSTREAM_UNAVAILABLE') from None
        operation.login_id = identifier
        url, code = response.get('verificationUrl'), response.get('userCode')
        require(response.get('type') == 'chatgptDeviceCode' and type(url) is str and len(url) <= 500)
        parsed = urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname == 'auth.openai.com'
                and not parsed.username and not parsed.password and parsed.port is None
                and not parsed.query and not parsed.fragment and not any(c.isspace() for c in url))
        require(type(code) is str and re.fullmatch(r'[A-Za-z0-9]{4,8}(?:-[A-Za-z0-9]{4,8})?', code)
                and 8 <= len(code) <= 17)
        # 协议没有官方expiresAt；这里只估计展示期限，另留有界时间接收完成通知。
        operation.challenge = {'operation_id': operation.public['id'], 'verification_url': url, 'user_code': code,
                               'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=self.login_timeout)).isoformat()}
        deadline = asyncio.get_running_loop().time() + self.login_timeout + self.login_completion_grace
        while True:
            operation.stage = 'login_wait'
            remaining = deadline - asyncio.get_running_loop().time()
            expired = remaining <= 0
            if not expired:
                try:
                    events = [await operation.session.notification(remaining)]
                except (TimeoutError, RuntimeErrorCode) as error:
                    if isinstance(error, RuntimeErrorCode) and error.code != 'TIMEOUT':
                        raise
                    expired = True
            if expired:
                events = operation.session.take_queued_notifications()
            self.current(operation)
            for event in events:
                if event.get('method') != 'account/login/completed':
                    continue
                params = event.get('params') or {}
                if params.get('loginId') != operation.login_id:
                    continue
                require(params.get('success') is True, 'AUTH_REQUIRED')
                operation.challenge = None
                operation.login_id = None
                await self.refresh(operation)
                return
            require(not expired, 'TIMEOUT')

    async def logout(self, operation):
        operation.stage = 'logout'
        await operation.session.request('account/logout', {})
        require(await self.read_account(operation) is None)
        await self.close_session(operation)

    async def test_model(self, operation, *, items=None, schema=None):
        await self.refresh(operation)
        model = operation.params['model']
        operation.stage = 'model_validation'
        require(model in {item['id'] for item in self.models}, 'MODEL_UNAVAILABLE')
        operation.stage = 'thread_start'
        result = await operation.session.request('thread/start', {'model': model, 'cwd': '/work/current',
            'approvalPolicy': 'never', 'ephemeral': True, 'environments': [], 'dynamicTools': []})
        thread = result.get('thread') or {}
        require(thread.get('ephemeral') is True and thread.get('environments') == [] and 'environments' in thread
                and type(thread.get('id')) is str and result.get('approvalPolicy') == 'never' and result.get('model') == model)
        operation.stage = 'mcp_status'
        status = await operation.session.request('mcpServerStatus/list', {'threadId': thread['id']})
        require(status.get('data') == [] and status.get('nextCursor') is None)
        operation.stage = 'turn_start'
        started = await operation.session.request('turn/start', {'threadId': thread['id'], 'environments': [],
            'input': items if items is not None else [{'type': 'text', 'text': TEST_PROMPT, 'text_elements': []}],
            'outputSchema': schema if schema is not None else {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                             'required': ['ok'], 'additionalProperties': False}})
        turn_id = (started.get('turn') or {}).get('id')
        require(type(turn_id) is str and turn_id)
        operation.turn = {'threadId': thread['id'], 'turnId': turn_id}
        deadline, final_text, last_error = asyncio.get_running_loop().time() + 300, None, None
        while True:
            operation.stage = 'turn_events'
            require(deadline > asyncio.get_running_loop().time(), 'TIMEOUT')
            event = await operation.session.notification(deadline - asyncio.get_running_loop().time())
            params = event.get('params') or {}
            if params.get('threadId') != thread['id']:
                continue
            if event.get('method') == 'error' and params.get('turnId') == turn_id:
                last_error = turn_error_summary(params.get('error'))
                retry = params.get('willRetry')
                last_error['will_retry'] = retry if type(retry) is bool else None
                print(json.dumps({'event': 'model_turn_error', **last_error}), file=sys.stderr, flush=True)
            if event.get('method') in {'item/started', 'item/completed'} and params.get('turnId') == turn_id:
                item = params.get('item') or {}
                require(item.get('type') not in TOOL_TYPES)
                if event['method'] == 'item/completed' and item.get('type') == 'agentMessage' and item.get('phase') != 'commentary':
                    require(type(item.get('text')) is str and len(item['text'].encode()) <= (2 * 1024 * 1024 if schema else 4096))
                    final_text = item['text']
            if event.get('method') == 'turn/completed' and (params.get('turn') or {}).get('id') == turn_id:
                # 匹配终态事件即结束活动turn；内容不合格也不能再次interrupt已结束的turn。
                operation.turn = None
                operation.stage = 'turn_completed'
                turn = params['turn']
                status = turn.get('status')
                diagnostic = {'event': 'model_turn_result',
                    'turn_status': status if type(status) is str and status in TURN_STATUSES else 'UNKNOWN',
                    'error_present': turn.get('error') is not None, 'cancel_requested': operation.cancel_requested,
                    'last_error': last_error, **turn_error_summary(turn.get('error'))}
                print(json.dumps(diagnostic), file=sys.stderr, flush=True)
                if status == 'failed' and diagnostic['codex_error_info'] == 'usageLimitExceeded':
                    raise RuntimeErrorCode('USAGE_LIMIT_EXCEEDED')
                require(params['turn'].get('status') == 'completed')
                operation.stage = 'final_json'
                require(final_text is not None)
                final = strict_json(final_text)
                if schema is None:
                    require(final == {'ok': True} and type(final.get('ok')) is bool)
                return final

    async def stop_and_reconcile(self, operation):
        operation.challenge = None
        cancellation_error = None
        if operation.session:
            try:
                if operation.login_id:
                    response = await operation.session.request('account/login/cancel', {'loginId': operation.login_id}, timeout=10)
                    require(response.get('status') in {'canceled', 'notFound'})
                if operation.turn:
                    await operation.session.request('turn/interrupt', operation.turn, timeout=10)
            except Exception as error:
                cancellation_error = RuntimeErrorCode('INTERRUPTED')
                report_error('official_cancel', error)
            finally:
                await self.close_session(operation)
        operation.login_id = operation.turn = None
        # 旧进程退出后另起只读会话；取消与授权完成竞争时仍报告真实账号状态。
        await self.open_session(operation)
        try:
            await self.read_account(operation)
        finally:
            await self.close_session(operation)
        if cancellation_error:
            raise cancellation_error

    async def _execute(self, operation):
        state, error_code = 'SUCCEEDED', ''
        operation.started = True
        try:
            if operation.cancel_requested:
                raise asyncio.CancelledError()
            action = operation.params['action']
            timeout = self.operation_timeout
            if action in {'login', 'switch'}:
                # 保留原启动/刷新预算；900秒总上限不能截断1020秒设备码等待。
                timeout += self.login_timeout + self.login_completion_grace
            async with asyncio.timeout(timeout):
                await self.open_session(operation)
                if action in {'switch', 'disconnect'}:
                    await self.logout(operation)
                if action == 'switch':
                    await self.open_session(operation)
                    await self.login(operation)
                elif action == 'login':
                    await self.login(operation)
                elif action == 'refresh':
                    await self.refresh(operation)
                elif action == 'test':
                    await self.test_model(operation)
                elif action in ('discover', 'extract'):
                    from .parsing import parse_model
                    await parse_model(self, operation)
        except asyncio.CancelledError:
            state, error_code = 'CANCELED', ''
        except (TimeoutError, RuntimeErrorCode) as error:
            state = 'FAILED'
            error_code = error.code if isinstance(error, RuntimeErrorCode) else 'TIMEOUT'
            report_primary_failure(operation, error_code)
        except Exception as error:
            state, error_code = 'FAILED', 'UPSTREAM_UNAVAILABLE'
            report_primary_failure(operation, error_code)
            report_error('operation', error)
        finally:
            operation.cleaning = True
            operation.challenge = None
            try:
                needs_reconcile = (operation.cancel_requested or operation.login_id or operation.turn
                                   or operation.params['action'] in {'login', 'switch', 'disconnect'})
                if (state != 'SUCCEEDED' or operation.cancel_requested) and needs_reconcile:
                    if operation.cancel_requested:
                        state, error_code = 'CANCELED', ''
                    await asyncio.wait_for(self.stop_and_reconcile(operation), 90)
                else:
                    await self.close_session(operation)
                if operation.cancel_requested:
                    state, error_code = 'CANCELED', ''
            except BaseException as error:
                self.unavailable = True
                state, error_code = 'FAILED', 'INTERRUPTED'
                report_error('operation_cleanup', error)
                # 清理本身超时/取消后仍尝试终止同一子进程，不释放为可接新任务状态。
                try:
                    await asyncio.wait_for(self.close_session(operation), 20)
                except BaseException as error:
                    operation.cleanup_failed = True
                    report_error('operation_cleanup_retry', error)
            operation.public.update(state=state, error_code=error_code, completed_at=now())
            operation.params.pop('payload', None)
            if state != 'SUCCEEDED':
                operation.result = None
            if self.active is operation:
                self.active = None

    async def close(self):
        self.closing = True
        if self.active:
            operation = self.active
            if not operation.cancel_requested:
                operation.cancel_requested = True
                operation.challenge = None
                if operation.started and not operation.cleaning:
                    operation.task.cancel()
            await operation.task
        for operation in self.operations.values():
            if operation.session is not None:
                await asyncio.wait_for(self.close_session(operation), 20)

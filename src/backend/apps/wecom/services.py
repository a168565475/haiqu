import hashlib
import re
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth import SESSION_KEY, get_user_model, login as django_login
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404

from apps.access_control.management_permissions import require_wecom_manager as require_manager
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee
from .client import WeComClient, WeComError
from .credentials import CredentialError, decrypt_secret, encrypt_secret
from .directory_selectors import normalized_name
from .models import OAuthState, WeComBinding, WeComConfig
from .selectors import config_etag, config_snapshot, configuration_complete, get_config, waiting_for_role


class OAuthFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def audit(request, instance, action, *, actor=None, user_id="", employee_name="", result="SUCCESS", message="", before=None, after=None):
    safe_after = {"user_id": user_id, "employee_name": employee_name, "result": result, "message": message}
    if after:
        safe_after.update(after)
    return write_audit_log(object_type="WECOM", object_id=instance.pk, action=action,
                           actor_employee=actor, before_data=before, after_data=safe_after, request=request)


def require_etag(value, expected):
    if not value:
        raise PreconditionRequired()
    if value != expected:
        raise PreconditionFailed()


def _constraint_name(exc):
    return getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)


@transaction.atomic
@sensitive_variables()
def update_config(request, data):
    actor = require_manager(request)
    config = WeComConfig.objects.select_for_update().first() or WeComConfig()
    require_etag(request.headers.get("If-Match"), config_etag(config))
    before = config_snapshot(config)
    if data.get("corp_id", config.corp_id) != config.corp_id and WeComBinding.objects.exists():
        raise Conflict("已有成员绑定，不能直接更换企业 ID。")
    login_changed = any(field in data and data[field] != getattr(config, field) for field in ("corp_id", "agent_id", "erp_origin"))
    for field in ("corp_id", "agent_id", "erp_origin", "enabled"):
        if field in data:
            setattr(config, field, data[field])
    for field in ("secret", "callback_token", "callback_aes_key"):
        if not data.get(field):
            continue
        ciphertext = getattr(config, field + "_ciphertext")
        try:
            current_value = decrypt_secret(ciphertext) if ciphertext else ""
        except CredentialError:
            # 已无法读取的旧凭据仍可被管理员提交的新值修复。
            current_value = None
        if data[field] != current_value:
            setattr(config, field + "_ciphertext", encrypt_secret(data[field]))
            if field == "secret":
                login_changed = True
    if config.enabled and not configuration_complete(config):
        raise ValidationError({"enabled": "请先完整保存网页登录配置并配置服务器加密密钥。"})
    if login_changed:
        config.last_check_status, config.last_check_message, config.last_checked_at = "NOT_CHECKED", "", None
    try:
        with transaction.atomic():
            config.save()
    except IntegrityError as exc:
        if _constraint_name(exc) == "wecom_config_singleton_key":
            raise PreconditionFailed() from exc
        raise
    audit(request, config, "CONFIG_UPDATE", actor=actor, before=before, after=config_snapshot(config), message="企业微信配置已更新。")
    return config


@sensitive_variables()
def check_connection(request):
    require_manager(request)
    config = get_config()
    require_etag(request.headers.get("If-Match"), config_etag(config))
    if config._state.adding or not configuration_complete(config):
        raise Conflict("请先完整保存网页登录配置。")
    expected = config_etag(config)
    try:
        WeComClient(config).check_connection()
        status, message = "SUCCESS", "官方应用接口连接成功；尚未验证真实工作台登录。"
    except WeComError as exc:
        # 客户端只提供固定安全文案，第三方原始 errmsg 不进入此处。
        status, message = "FAILED", exc.message[:250]
    with transaction.atomic():
        locked = WeComConfig.objects.select_for_update().get(pk=config.pk)
        require_etag(expected, config_etag(locked))
        locked.last_check_status, locked.last_check_message, locked.last_checked_at = status, message, timezone.now()
        locked.save(update_fields=["last_check_status", "last_check_message", "last_checked_at", "updated_at"])
        audit(request, locked, "CONFIG_CHECK", actor=require_manager(request), result=status, message=message)
    return locked


def validate_member(member, expected_user_id):
    user_id, name = member.get("userid"), member.get("name")
    if not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", user_id) or user_id.lower() != expected_user_id.lower():
        raise OAuthFailure("MEMBER_REJECTED")
    if member.get("status") != 1 or isinstance(member.get("status"), bool) or not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
        raise OAuthFailure("MEMBER_REJECTED")
    return {"userid": user_id, "name": name.strip()}


def _new_user(name):
    user = get_user_model()(username="wecom_" + uuid.uuid4().hex, first_name=name, is_active=True, is_staff=False, is_superuser=False)
    user.set_unusable_password()
    user.save()
    return user


def _assert_employee_active(employee, user):
    if employee.status != "ACTIVE" or employee.archived_at is not None or user is None or not user.is_active:
        raise OAuthFailure("ACCOUNT_INACTIVE")


def _locked_employee_and_user(employee_id):
    # 与现有账号停用保持相同顺序；NO KEY UPDATE 不阻塞审计外键读取。
    employee = get_object_or_404(Employee.objects.select_for_update(no_key=True), pk=employee_id)
    user = get_user_model().objects.select_for_update().get(pk=employee.user_id) if employee.user_id else None
    return employee, user


def _existing_binding(corp_id, user_id):
    return WeComBinding.objects.filter(corp_id=corp_id, user_id__iexact=user_id).select_related("employee__user").first()


def _create_binding(config, member, employee, *, source, created_account, actor=None):
    return WeComBinding.objects.create(corp_id=config.corp_id, user_id=member["userid"], member_name=member["name"],
                                       employee=employee, source=source, created_account=created_account, created_by_employee=actor)


@sensitive_variables()
def bind_employee(request, data):
    actor = require_manager(request)
    try:
        return _bind_employee(request, data)
    except (Conflict, OAuthFailure, WeComError, CredentialError):
        # 失败业务事务已回滚；另记受限审计，不能随失败绑定一起回滚。
        config = WeComConfig.objects.first()
        if config is not None:
            audit(request, config, "MANUAL_BIND_FAILED", actor=actor, user_id=data["user_id"],
                  result="FAILED", message="成员绑定被拒绝，请核对成员有效性、员工状态和已有绑定。")
        raise


@sensitive_variables()
def _bind_employee(request, data):
    actor = require_manager(request)
    config = get_config()
    if config._state.adding or not configuration_complete(config):
        raise Conflict("请先完整保存网页登录配置。")
    employee = get_object_or_404(Employee, pk=data["employee_id"])
    require_matching_etag(request, employee)
    member = validate_member(WeComClient(config).get_member(data["user_id"]), data["user_id"])
    with transaction.atomic():
        locked_config = WeComConfig.objects.select_for_update().get(pk=config.pk)
        require_etag(config_etag(config), config_etag(locked_config))
        employee, user = _locked_employee_and_user(employee.pk)
        require_matching_etag(request, employee)
        if employee.status != "ACTIVE" or employee.archived_at is not None or (user and not user.is_active):
            raise Conflict("只能绑定有效员工及启用的账号。")
        existing = _existing_binding(config.corp_id, member["userid"])
        if existing:
            if existing.employee_id == employee.pk:
                return existing
            raise Conflict("此企业微信成员已绑定其他员工，不能覆盖或自动合并。")
        if WeComBinding.objects.filter(employee=employee).exists():
            raise Conflict("所选员工已绑定企业微信成员，不能覆盖。")
        created_account = user is None
        if created_account:
            user = _new_user(employee.display_name)
            employee.user = user
            employee.save(update_fields=["user", "updated_at"])
        try:
            with transaction.atomic():
                binding = _create_binding(config, member, employee, source="MANUAL", created_account=created_account, actor=actor)
        except IntegrityError as exc:
            if _constraint_name(exc) not in {"wecom_corp_user_ci_unique", "wecom_binding_employee_id_key"}:
                raise
            existing = _existing_binding(config.corp_id, member["userid"])
            if existing and existing.employee_id == employee.pk:
                return existing
            raise Conflict("绑定已被其他请求修改，请刷新核对。") from exc
        audit(request, binding, "MANUAL_BIND", actor=actor, user_id=binding.user_id, employee_name=employee.display_name, message="管理员确认并绑定已有员工。")
        return binding


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@sensitive_variables()
def create_oauth_state(request, config):
    if not request.session.session_key:
        request.session.create()
    state = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        # 仅清理本模块过期的随机挑战，不触碰登录会话或业务审计。
        OAuthState.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
        OAuthState.objects.create(state_digest=_digest(state), session_digest=_digest(request.session.session_key),
                                  initiator_user_id=request.user.pk if request.user.is_authenticated else None,
                                  config_etag=config_etag(config), expires_at=now + timedelta(minutes=5))
    return state


@sensitive_variables()
def create_qr_challenge(request, config, next_path):
    state = create_oauth_state(request, config)
    challenge = _remember_oauth_return_path(request, state, next_path)
    return {"login_type": "CorpApp", "appid": config.corp_id, "agentid": config.agent_id,
            "redirect_uri": config.erp_origin + "/api/auth/wecom/callback/", "state": state,
            "expires_at": challenge.expires_at}


@sensitive_variables()
def _remember_oauth_return_path(request, state, next_path):
    challenge = OAuthState.objects.get(state_digest=_digest(state))
    now = timezone.now().timestamp()
    # 回跳信息保存在发起方Session，并与挑战摘要关联；不向官方发送业务地址。
    redirects = {key: value for key, value in request.session.get("wecom_qr_redirects", {}).items()
                 if value["expires_at"] > now}
    redirects[challenge.state_digest] = {"path": next_path, "expires_at": challenge.expires_at.timestamp()}
    request.session["wecom_qr_redirects"] = redirects
    return challenge


@sensitive_variables()
def cancel_oauth_state(request, state):
    if not request.session.session_key:
        return
    digest = _digest(state)
    # 与回调共用条件更新；重复取消、未知状态及其他会话均不泄露状态是否存在。
    OAuthState.objects.filter(state_digest=digest, session_digest=_digest(request.session.session_key),
                              consumed_at__isnull=True).update(consumed_at=timezone.now())
    redirects = request.session.get("wecom_qr_redirects", {})
    if digest in redirects:
        del redirects[digest]
        request.session["wecom_qr_redirects"] = redirects


@sensitive_variables()
def consume_oauth_state(request, state):
    if not isinstance(state, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state) or not request.session.session_key:
        raise OAuthFailure("INVALID_STATE")
    rows = OAuthState.objects.filter(state_digest=_digest(state), session_digest=_digest(request.session.session_key),
                                     expires_at__gt=timezone.now(), consumed_at__isnull=True)
    with transaction.atomic():
        row = rows.first()
        # 条件更新由数据库串行裁决，两个回调不能同时消费同一个状态。
        if row is None or rows.update(consumed_at=timezone.now()) != 1:
            raise OAuthFailure("INVALID_STATE")
    current_user_id = request.user.pk if request.user.is_authenticated else None
    if current_user_id != row.initiator_user_id:
        raise OAuthFailure("ACCOUNT_MISMATCH")
    return row


@sensitive_variables()
def oauth_url(request, config, next_path="/"):
    state = create_oauth_state(request, config)
    _remember_oauth_return_path(request, state, next_path)
    parameters = {"appid": config.corp_id, "redirect_uri": config.erp_origin + "/api/auth/wecom/callback/",
                  "response_type": "code", "scope": "snsapi_base", "state": state, "agentid": config.agent_id}
    return "https://open.weixin.qq.com/connect/oauth2/authorize?" + urlencode(parameters) + "#wechat_redirect"


@sensitive_variables()
def oauth_login(request, state, code):
    challenge = consume_oauth_state(request, state)
    redirects = request.session.get("wecom_qr_redirects", {})
    return_path = redirects.get(challenge.state_digest, {}).get("path", "/")
    if not isinstance(code, str) or not code or len(code) > 512:
        raise OAuthFailure("INVALID_REQUEST")
    config = get_config()
    if config._state.adding or not config.enabled or not configuration_complete(config) or challenge.config_etag != config_etag(config):
        raise OAuthFailure("CONFIG_UNAVAILABLE")
    client = WeComClient(config)
    identity = client.get_identity(code)
    user_id = identity.get("userid")
    if not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", user_id) or identity.get("corpid", config.corp_id) != config.corp_id:
        raise OAuthFailure("MEMBER_REJECTED")
    member = validate_member(client.get_member(user_id), user_id)
    with transaction.atomic():
        locked_config = WeComConfig.objects.select_for_update().get(pk=config.pk)
        if not locked_config.enabled or config_etag(locked_config) != challenge.config_etag:
            raise OAuthFailure("CONFIG_UNAVAILABLE")
        binding = _existing_binding(config.corp_id, user_id)
        # 已登录 A 时，必须先找到属于 A 的既有绑定；绝不为返回的 B 建档。
        if request.user.is_authenticated and (binding is None or binding.employee.user_id != request.user.pk):
            raise OAuthFailure("ACCOUNT_MISMATCH")
        if binding is None:
            # 姓名只用于提示人工核对；历史、停用员工也可能是同一人，不能另建或自动合并。
            member_name = normalized_name(member["name"])
            if any(normalized_name(name) == member_name
                   for name in Employee.objects.values_list("display_name", flat=True).iterator()):
                raise OAuthFailure("BINDING_REQUIRED")
            try:
                with transaction.atomic():
                    user = _new_user(member["name"])
                    employee = Employee.objects.create(employee_code="WECOM-" + uuid.uuid4().hex.upper(), display_name=member["name"], user=user)
                    binding = _create_binding(config, member, employee, source="AUTO", created_account=True)
                    audit(request, binding, "AUTO_CREATE", user_id=binding.user_id, employee_name=employee.display_name, message="企业微信首次访问创建员工及待授权账号。")
            except IntegrityError as exc:
                if _constraint_name(exc) != "wecom_corp_user_ci_unique":
                    raise
                binding = _existing_binding(config.corp_id, user_id)
                if binding is None:
                    raise
        employee, user = _locked_employee_and_user(binding.employee_id)
        _assert_employee_active(employee, user)
        if request.user.is_authenticated and request.user.pk != user.pk:
            raise OAuthFailure("ACCOUNT_MISMATCH")
        # 与密码登录/停用的user→session锁顺序保持一致。上游请求期间原会话
        # 可能已被另一个标签页轮换或退出，不能凭请求里的旧缓存再建立登录。
        login_session = Session.objects.select_for_update().filter(
            session_key=request.session.session_key, expire_date__gt=timezone.now()).first()
        expected_user_id = str(challenge.initiator_user_id) if challenge.initiator_user_id is not None else None
        if login_session is None or login_session.get_decoded().get(SESSION_KEY) != expected_user_id:
            raise OAuthFailure("ACCOUNT_MISMATCH")
        # 验证成功前不修改Session，避免失败响应写回已删除的旧会话或覆盖新Cookie。
        if challenge.state_digest in redirects:
            del redirects[challenge.state_digest]
            request.session["wecom_qr_redirects"] = redirects
        django_login(request, user, backend="apps.core.auth.ErpModelBackend")
        request.session.save()
        from apps.core.login_records import record_successful_login
        record_successful_login(request, user, "WECOM")
        audit(request, binding, "OAUTH_LOGIN", user_id=binding.user_id, employee_name=employee.display_name, message="企业微信身份登录成功。")
        return "/auth/waiting-role" if waiting_for_role(user) else return_path


def audit_login_failure(request, code):
    config = WeComConfig.objects.first()
    if config is not None:
        audit(request, config, "OAUTH_LOGIN_FAILED", result="FAILED", message="企业微信登录被拒绝：" + code)

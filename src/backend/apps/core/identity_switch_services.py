"""Real-account switching using only Django's existing database sessions.

The root login is a revocable proof, never a usable browser identity once marked.
The separate, auth-less control session is not a business/audit record. All reads
and writes of a chain run under the middleware's PostgreSQL advisory lock.
"""
import hashlib
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model,
    load_backend, login as django_login,
)
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.dispatch import receiver
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables

from .identity_switch_selectors import is_switch_admin, switch_targets

MARKER = "_account_switch"
VERSION = "_identity_version"
NONCE = "_identity_login_nonce"
KIND = "admin-account-switch-v1"
KEY_PATTERN = re.compile(r"[a-z0-9]{32}\Z")


class IdentitySwitchError(Exception):
    def __init__(self, code, message, status=403):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


@dataclass(repr=False)
class SwitchContext:
    root: str
    control_key: str = ""
    control: dict | None = None
    capability: bool = False
    stale: bool = False
    invalid: bool = False


def return_cookie_name():
    # AUTH is redacted by both Django's and WeCom's exception filters, even
    # when a downstream callback replaces the request-specific filter.
    return settings.SESSION_COOKIE_NAME + "_admin_return_auth"


@sensitive_variables()
def _key(value):
    return value if isinstance(value, str) and KEY_PATTERN.fullmatch(value) else ""


@sensitive_variables()
def session_row(key):
    return Session.objects.filter(session_key=_key(key)).first() if _key(key) else None


@sensitive_variables()
def initial_admin_root(session_key):
    """Only an ordinary original admin session can start a new chain.

    Unrelated employee/anonymous OAuth requests retain their existing lifecycle
    concurrency; flow sessions are located independently by their marker/cookie.
    """
    row = session_row(session_key)
    user_id = row.get_decoded().get(SESSION_KEY) if row else None
    if not isinstance(user_id, str) or not user_id.isdecimal():
        return ""
    user = get_user_model().objects.filter(pk=user_id).first()
    return _key(session_key) if is_switch_admin(user) else ""


@sensitive_variables()
def _marker(data):
    value = data.get(MARKER)
    if isinstance(value, dict) and _key(value.get("root")) and _key(value.get("control")):
        return value
    return None


@sensitive_variables()
def locate_context(session_key, capability_key):
    """Locate before locking, then call again under the lock before using it."""
    row = session_row(session_key)
    data = row.get_decoded() if row else {}
    marker = _marker(data)
    damaged_marker = MARKER in data and marker is None
    control_key = marker["control"] if marker else _key(capability_key)
    control_row = session_row(control_key)
    control = control_row.get_decoded() if control_row else None
    if not control or control.get("kind") != KIND or not _key(control.get("root")):
        if marker:
            return SwitchContext(marker["root"], control_key, invalid=True)
        return SwitchContext(_key(session_key), invalid=True) if damaged_marker else None
    ctx = SwitchContext(control["root"], control_key, control)
    ctx.capability = bool(_key(capability_key) and constant_time_compare(control_key, capability_key))
    ctx.invalid = bool(
        damaged_marker or control_row.expire_date <= timezone.now()
        or bool(capability_key and not ctx.capability)
        or not _key(control.get("current"))
        or not isinstance(control.get("version"), str) or not control.get("version")
        or not isinstance(control.get("nonce"), str) or not control.get("nonce")
        or (marker and marker["root"] != ctx.root)
    )
    # A lost/deleted current employee session is recoverable. A DIFFERENT
    # session, including the original root, must never silently become current.
    ctx.stale = bool(session_key and session_key != control.get("current"))
    if row and (not marker or marker["control"] != control_key):
        ctx.stale = True
    if row and session_key == control.get("current") and str(row.get_decoded().get(SESSION_KEY)) != str(
        control.get("current_user_id")
    ):
        ctx.invalid = True
    return ctx


@sensitive_variables()
def lock_number(root):
    digest = hashlib.sha256((KIND + ":" + root).encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
@sensitive_variables()
def chain_lock(root):
    """Session-level lock preserves existing business transaction boundaries.

    Never proceed after a reconnect: a new physical connection does not own the
    lock. The execute wrapper also catches reconnects occurring inside a view.
    """
    connection.ensure_connection()
    physical = connection.connection
    number = lock_number(root)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", [number])

    @sensitive_variables()
    def same_connection(execute, sql, params, many, context):
        if connection.connection is not physical:
            raise DatabaseError("Identity session connection changed")
        return execute(sql, params, many, context)

    try:
        with connection.execute_wrapper(same_connection):
            yield
            if connection.connection is not physical:
                raise DatabaseError("Identity session connection changed")
    finally:
        if connection.connection is not physical:
            # A detached old connection must not retain our session-level lock.
            if not physical.closed:
                physical.close()
        elif not physical.closed:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [number])
                    if not cursor.fetchone()[0]:
                        raise DatabaseError("Identity session lock was lost")
            except DatabaseError:
                # In particular, do not return an aborted transaction with a
                # still-held session lock to CONN_MAX_AGE connection reuse.
                connection.close()
                raise


def raw_request(request):
    return getattr(request, "_request", request)


def identity_version(request):
    request = raw_request(request)
    ctx = getattr(request, "_identity_context", None)
    if ctx and ctx.control and not getattr(request, "_identity_revoked", False):
        return ctx.control["version"]
    if not request.session.get(VERSION):
        request.session[VERSION] = secrets.token_urlsafe(32)
    return request.session[VERSION]


def require_version(request):
    value = request.META.get("HTTP_X_IDENTITY_VERSION", "")
    if not value:
        raise IdentitySwitchError("IDENTITY_VERSION_REQUIRED", "请先获取当前身份版本。", 428)
    if not constant_time_compare(value, identity_version(request)):
        raise IdentitySwitchError("IDENTITY_VERSION_CONFLICT", "身份已变化，请重新获取当前身份。", 409)


@sensitive_variables()
def _validated_admin(root_row, ctx=None):
    if root_row is None or root_row.expire_date <= timezone.now():
        raise IdentitySwitchError("ADMIN_LOGIN_EXPIRED", "原管理员登录已失效，请重新登录。")
    data = root_row.get_decoded()
    backend = data.get(BACKEND_SESSION_KEY)
    if backend not in settings.AUTHENTICATION_BACKENDS:
        raise IdentitySwitchError("ADMIN_LOGIN_EXPIRED", "原管理员登录已失效，请重新登录。")
    try:
        user = load_backend(backend).get_user(data.get(SESSION_KEY))
    except (TypeError, ValueError, get_user_model().DoesNotExist):
        user = None
    if not is_switch_admin(user):
        raise IdentitySwitchError("ADMIN_LOGIN_EXPIRED", "原管理员资格已失效，请重新登录。")
    hashes = [user.get_session_auth_hash(), *user.get_session_auth_fallback_hash()]
    if not any(constant_time_compare(data.get(HASH_SESSION_KEY, ""), value) for value in hashes):
        raise IdentitySwitchError("ADMIN_LOGIN_EXPIRED", "原管理员登录已失效，请重新登录。")
    if ctx:
        marker = _marker(data)
        if (
            not marker or marker["control"] != ctx.control_key or marker["root"] != ctx.root
            or not data.get(NONCE) or data[NONCE] != ctx.control.get("nonce")
        ):
            raise IdentitySwitchError("ADMIN_LOGIN_EXPIRED", "原管理员登录已失效，请重新登录。")
    return user, data, backend


@sensitive_variables()
def authorize_switch(request):
    raw = raw_request(request)
    ctx = getattr(raw, "_identity_context", None)
    if ctx:
        if ctx.invalid or ctx.stale or not ctx.control or not ctx.capability:
            raise IdentitySwitchError("SWITCH_NOT_ALLOWED", "需要有效的原管理员登录。")
        user, _, _ = _validated_admin(session_row(ctx.root), ctx)
        return user
    if not is_switch_admin(request.user):
        raise IdentitySwitchError("SWITCH_NOT_ALLOWED", "仅 admin 管理员可以切换账号。")
    user, _, _ = _validated_admin(session_row(raw.session.session_key))
    return user


def switch_state(request):
    raw = raw_request(request)
    ctx = getattr(raw, "_identity_context", None)
    if ctx and ctx.control and not getattr(raw, "_identity_revoked", False):
        can_return = False
        if ctx.control.get("active") and ctx.capability and not ctx.invalid and not ctx.stale:
            try:
                _validated_admin(session_row(ctx.root), ctx)
                can_return = True
            except IdentitySwitchError:
                pass
        return {"active": bool(ctx.control.get("active")), "can_return": can_return,
                "identity_version": ctx.control["version"]}
    if is_switch_admin(request.user):
        return {"active": False, "can_return": False, "identity_version": identity_version(request)}
    return None


@sensitive_variables()
def _save_control(key, data, expires):
    store = SessionStore(session_key=key or None)
    store.update(data)
    store.set_expiry(expires)
    if key:
        store.save()
    else:
        store.create()
    return store.session_key


@sensitive_variables()
def _transition(request, employee_id=None, returning=False):
    """Lock employee -> user -> session, recheck proof, replace real identity."""
    from apps.organizations.models import Employee

    raw = raw_request(request)
    initiator = authorize_switch(request)
    ctx = getattr(raw, "_identity_context", None)
    if returning and (not ctx or not ctx.control.get("active")):
        raise IdentitySwitchError("RETURN_NOT_ALLOWED", "当前没有可返回的管理员登录。")
    require_version(request)
    root = ctx.root if ctx else raw.session.session_key
    original_id = initiator.pk
    employee = switch_targets().filter(pk=employee_id).first() if not returning else None
    if not returning and employee is None:
        raise IdentitySwitchError("SWITCH_TARGET_UNAVAILABLE", "员工账号不存在或不可切换。", 404)
    user_ids = {str(original_id)}
    if employee:
        user_ids.add(str(employee.user_id))
    if ctx and ctx.control.get("current_user_id"):
        user_ids.add(str(ctx.control["current_user_id"]))

    old_session, old_user = raw.session, request.user
    old_csrf = {key: raw.META.get(key) for key in ("CSRF_COOKIE", "CSRF_COOKIE_NEEDS_UPDATE")}
    try:
        with transaction.atomic():
            employee_filter = Q(user_id__in=user_ids)
            if employee_id:
                employee_filter |= Q(pk=employee_id)
            employees = list(Employee.objects.select_for_update(no_key=True).filter(employee_filter).order_by("pk"))
            # A binding can change between the preliminary lookup and the
            # employee lock. Lock the NOW-bound account before validating it.
            user_ids.update(str(item.user_id) for item in employees if item.user_id is not None)
            list(get_user_model().objects.select_for_update().filter(pk__in=user_ids).order_by("pk"))
            keys = {root}
            if ctx:
                keys.add(ctx.control["current"])
            rows = {row.session_key: row for row in Session.objects.select_for_update().filter(
                session_key__in=keys).order_by("session_key")}
            admin, root_data, backend = _validated_admin(rows.get(root), ctx)
            if str(admin.pk) != str(original_id):
                raise IdentitySwitchError("ADMIN_LOGIN_EXPIRED", "原管理员登录已变化。")
            if not returning:
                employee = switch_targets().filter(pk=employee_id).first()
                if employee is None:
                    raise IdentitySwitchError("SWITCH_TARGET_UNAVAILABLE", "员工账号已失效。", 409)
                user = employee.user
            else:
                user = admin
            expires = rows[root].expire_date
            control = dict(ctx.control) if ctx else {
                "kind": KIND, "root": root,
                "nonce": root_data.get(NONCE) or secrets.token_urlsafe(32),
                "browser_close": old_session.get_expire_at_browser_close(),
            }
            control_key = ctx.control_key if ctx else _save_control("", control, expires)
            marker = {"root": root, "control": control_key}
            if not ctx:
                root_store = SessionStore(session_key=root)
                root_store.update(root_data)
                root_store[NONCE] = control["nonce"]
                root_store[MARKER] = marker
                root_store.set_expiry(expires)
                root_store.save()
            # Never login on the root store: cross-account Django login flushes it.
            raw.session = SessionStore()
            raw._identity_internal_login = True
            try:
                django_login(raw, user, backend=backend)
            finally:
                raw._identity_internal_login = False
            request.user = user
            raw.session[MARKER] = marker
            raw.session.set_expiry(expires)
            raw.session.save()
            old_current = control.get("current")
            control.update(current=raw.session.session_key, current_user_id=str(user.pk),
                           active=not returning, version=secrets.token_urlsafe(32))
            _save_control(control_key, control, expires)
            if old_current and old_current != root:
                Session.objects.filter(session_key=old_current).delete()
        raw._identity_context = SwitchContext(root, control_key, control, capability=True)
        raw._identity_transition = True
        raw._identity_issue_cookie = (expires, control["browser_close"])
        raw._cached_user = user
        return user
    except Exception:
        raw.session = old_session
        request.user = old_user
        raw._cached_user = old_user
        for key, value in old_csrf.items():
            if value is None:
                raw.META.pop(key, None)
            else:
                raw.META[key] = value
        raise


def switch_account(request, employee_id):
    return _transition(request, employee_id=employee_id)


def return_admin(request):
    return _transition(request, returning=True)


@sensitive_variables()
def revoke_chain(request):
    """Called by successful explicit auth signals, inside auth-route transaction."""
    ctx = getattr(request, "_identity_context", None)
    marker = _marker(dict(request.session.items()))
    control_key = ctx.control_key if ctx else marker["control"] if marker else ""
    root = ctx.root if ctx else marker["root"] if marker else ""
    if not root and not control_key:
        return
    control_row = session_row(control_key)
    control = control_row.get_decoded() if control_row else {}
    keep = request.session.session_key
    keys = {root, control_key, control.get("current", "")} - {"", keep}
    Session.objects.filter(session_key__in=keys).delete()
    # Same-user login can keep its key. Remove old markers instead of deleting
    # the newly authenticated session. The root must cease being a proof.
    request.session.pop(MARKER, None)
    request.session.pop(VERSION, None)
    request._identity_revoked = True
    request._identity_clear_cookie = True


@receiver(user_logged_in, dispatch_uid="core.identity_switch.explicit_login")
@sensitive_variables()
def explicit_login(sender, request, user, **kwargs):
    if request is None:
        return
    request = raw_request(request)
    if getattr(request, "_identity_internal_login", False):
        return
    request._identity_explicit_event = True
    if getattr(request, "_identity_context", None) or _marker(dict(request.session.items())):
        # Same-account Django login otherwise preserves its key. Rotating is
        # essential: stale flow requests must not downgrade to an ordinary login.
        request.session.cycle_key()
    revoke_chain(request)
    request.session[NONCE] = secrets.token_urlsafe(32)
    request.session.pop(VERSION, None)
    request._identity_login_expected = (request.session.session_key, str(user.pk), request.session[NONCE])


@receiver(user_logged_out, dispatch_uid="core.identity_switch.explicit_logout")
@sensitive_variables()
def explicit_logout(sender, request, user, **kwargs):
    if request is None:
        return
    request = raw_request(request)
    if getattr(request, "_identity_natural_logout", False):
        return
    revoke_chain(request)
    request._identity_explicit_event = True

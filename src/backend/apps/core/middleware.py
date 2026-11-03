import uuid
from contextlib import nullcontext

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.cache import add_never_cache_headers, patch_vary_headers
from django.views.debug import SafeExceptionReporterFilter
from django.views.decorators.debug import sensitive_variables

from . import identity_switch_services as identity

from django.contrib.auth import logout as django_logout
from django.http import JsonResponse

from .auth import can_access_erp
from apps.wecom.selectors import waiting_for_role


class RequestIdMiddleware:
    header_name = "HTTP_X_REQUEST_ID"
    response_header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = self._request_id(request.META.get(self.header_name))
        response = self.get_response(request)
        response[self.response_header_name] = request.request_id
        return response

    @staticmethod
    def _request_id(value):
        if value:
            try:
                return str(uuid.UUID(value))
            except (TypeError, ValueError, AttributeError):
                pass
        return str(uuid.uuid4())


class ErpSessionAccessMiddleware:
    session_endpoints = {
        "/api/auth/me/", "/api/auth/login/", "/api/auth/logout/", "/api/health/",
        "/api/auth/wecom/start/", "/api/auth/wecom/callback/", "/api/auth/wecom/qr/",
        "/api/auth/switch-targets/", "/api/auth/switch/", "/api/auth/return-admin/",
        "/admin/login/", "/admin/logout/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from apps.access_control.superuser_services import sync_role_superuser
            sync_role_superuser(request.user)
        if request.user.is_authenticated and not can_access_erp(request.user):
            # Natural employee invalidation must not revoke the independent
            # return capability. Explicit logout remains a full chain revocation.
            request._identity_natural_logout = True
            try:
                django_logout(request)
            finally:
                request._identity_natural_logout = False
        elif (
            request.user.is_authenticated
            and request.path.startswith(("/api/", "/admin/"))
            and request.path not in self.session_endpoints
            and waiting_for_role(request.user)
        ):
            # 保留已验证的会话，让员工能查询授权状态或退出；业务访问仍由后端拦截。
            return JsonResponse({"error": {
                "code": "WECOM_ROLE_REQUIRED",
                "message": "等待管理员分配访问权限",
                "field_errors": {},
                "request_id": getattr(request, "request_id", None),
            }}, status=403)
        return self.get_response(request)


# Exact lifecycle exceptions, not an auth/admin path-prefix permission bypass.
IDENTITY_READ_ENDPOINTS = {"/api/auth/me/", "/api/auth/switch-targets/"}
IDENTITY_LIFECYCLE_ENDPOINTS = {
    "/api/auth/login/", "/api/auth/logout/", "/api/auth/wecom/start/",
    "/api/auth/wecom/callback/", "/api/auth/wecom/qr/",
    "/admin/login/", "/admin/logout/",
}
IDENTITY_TRANSITION_ENDPOINTS = {"/api/auth/switch/", "/api/auth/return-admin/"}
IDENTITY_TRANSACTION_ENDPOINTS = IDENTITY_LIFECYCLE_ENDPOINTS | IDENTITY_TRANSITION_ENDPOINTS
IDENTITY_VERSION_EXEMPT = IDENTITY_READ_ENDPOINTS | IDENTITY_LIFECYCLE_ENDPOINTS | {"/api/health/"}


def identity_error(request, exc):
    response = JsonResponse({"error": {
        "code": exc.code, "message": exc.message, "field_errors": {},
        "request_id": getattr(request, "request_id", None),
    }}, status=exc.status)
    add_never_cache_headers(response)
    return response


class IdentitySwitchExceptionReporterFilter(SafeExceptionReporterFilter):
    """Keep marked authentication locals private even in DEBUG responses."""

    def is_active(self, request):
        return True


class IdentitySwitchSessionMiddleware:
    """Outside SessionMiddleware: serialize load, execution AND response save."""

    def __init__(self, get_response):
        self.get_response = get_response

    @sensitive_variables()
    def __call__(self, request):
        incoming = request.COOKIES.get(settings.SESSION_COOKIE_NAME, "")
        capability = request.COOKIES.get(identity.return_cookie_name(), "")
        if incoming or capability or request.path.startswith(("/api/auth/", "/admin/")):
            # Install BEFORE the first sensitive lookup, without replacing an
            # upstream always-active filter. WeCom can also assign its own later;
            # AUTH cookies and sensitive_variables work with either filter.
            previous_filter = getattr(request, "exception_reporter_filter", None)
            if previous_filter is None or not previous_filter.is_active(request):
                request.exception_reporter_filter = IdentitySwitchExceptionReporterFilter()
        first = identity.locate_context(incoming, capability)
        root = first.root if first else identity.initial_admin_root(incoming)
        lock = identity.chain_lock(root) if root else nullcontext()
        try:
            with lock:
                # No cached session or user is reused after waiting for the lock.
                ctx = identity.locate_context(incoming, capability)
                request._identity_context = ctx
                if ctx and (ctx.invalid or ctx.stale) and request.path not in IDENTITY_LIFECYCLE_ENDPOINTS:
                    # A queued first switch still has the old root cookie and
                    # no capability cookie. It loses with a version conflict,
                    # never by authenticating that root as browser-current.
                    forbidden = ctx.invalid or (
                        ctx.stale and not ctx.capability and request.path not in IDENTITY_TRANSITION_ENDPOINTS)
                    code = "IDENTITY_CONTEXT_INVALID" if forbidden else "IDENTITY_VERSION_CONFLICT"
                    return identity_error(request, identity.IdentitySwitchError(
                        code, "身份会话已失效或已变化，请重新登录。", 403 if forbidden else 409))
                # Auth signals and later login audit failures share a transaction,
                # including Django admin login. Do not wrap ordinary business views.
                transactional = request.path in IDENTITY_TRANSITION_ENDPOINTS or bool(
                    ctx and request.path in IDENTITY_LIFECYCLE_ENDPOINTS)
                auth_transaction = transaction.atomic() if transactional else nullcontext()
                with auth_transaction:
                    response = self.get_response(request)
                    if transactional and response.status_code >= 400:
                        transaction.set_rollback(True)
                success = response.status_code < 400 and not getattr(request, "_identity_auth_failed", False)
                transition = success and (getattr(request, "_identity_transition", False) or getattr(
                    request, "_identity_explicit_event", False))
                # Normal delayed flow responses must not overwrite a new identity
                # cookie. The database also rejects replay of any old key.
                if (ctx and not transition) or not success:
                    response.cookies.pop(settings.SESSION_COOKIE_NAME, None)
                    response.cookies.pop(identity.return_cookie_name(), None)
                    # Only an explicit successful /me read may repair a missing
                    # CSRF cookie. Keep Django's generated cookie and attributes;
                    # never refresh a present cookie or relax identity protection.
                    recover_csrf = (
                        ctx and not ctx.invalid and not ctx.stale
                        and success and response.status_code == 200
                        and request.method == "GET" and request.path == "/api/auth/me/"
                        and settings.CSRF_COOKIE_NAME not in request.COOKIES
                    )
                    if not recover_csrf:
                        response.cookies.pop(settings.CSRF_COOKIE_NAME, None)
                if success and getattr(request, "_identity_clear_cookie", False):
                    response.delete_cookie(identity.return_cookie_name(), path=settings.SESSION_COOKIE_PATH,
                                           domain=settings.SESSION_COOKIE_DOMAIN, samesite=settings.SESSION_COOKIE_SAMESITE)
                if success and getattr(request, "_identity_issue_cookie", None):
                    expires, browser_close = request._identity_issue_cookie
                    # Keep the original browser-session cookie policy without
                    # letting SessionStore recompute the fixed DB deadline.
                    session_cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
                    if browser_close and session_cookie is not None:
                        session_cookie["max-age"] = ""
                        session_cookie["expires"] = ""
                    response.set_cookie(
                        identity.return_cookie_name(), request._identity_context.control_key,
                        max_age=None if browser_close else max(0, int((expires - timezone.now()).total_seconds())),
                        path=settings.SESSION_COOKIE_PATH, domain=settings.SESSION_COOKIE_DOMAIN,
                        secure=settings.SESSION_COOKIE_SECURE or request.is_secure(), httponly=True,
                        samesite=settings.SESSION_COOKIE_SAMESITE,
                    )
                if ctx or request.path.startswith("/api/auth/") or getattr(request, "_identity_transition", False):
                    add_never_cache_headers(response)
                    patch_vary_headers(response, ("Cookie",))
                return response
        except identity.IdentitySwitchError as exc:
            return identity_error(request, exc)
        except DatabaseError:
            # A lost physical connection also lost its advisory lock. Fail closed;
            # never continue on a replacement connection under an assumed lock.
            return identity_error(request, identity.IdentitySwitchError(
                "IDENTITY_SESSION_UNAVAILABLE", "身份会话暂不可用，请重试。", 503))


class IdentitySwitchGuardMiddleware:
    """After AuthenticationMiddleware, before ERP/role/business permission gates."""

    def __init__(self, get_response):
        self.get_response = get_response

    @sensitive_variables()
    def __call__(self, request):
        ctx = getattr(request, "_identity_context", None)
        if ctx and request.path.startswith(("/api/", "/admin/")) and request.path not in IDENTITY_VERSION_EXEMPT:
            try:
                identity.require_version(request)
            except identity.IdentitySwitchError as exc:
                return identity_error(request, exc)
        response = self.get_response(request)
        failed = response.status_code >= 400 and request.path in IDENTITY_TRANSACTION_ENDPOINTS
        expected = getattr(request, "_identity_login_expected", None)
        if expected and not failed and request.path != "/admin/login/":
            # WeCom catches some failures and redirects with HTTP 302 AFTER its
            # inner auth transaction rolled back. Status alone cannot authorize
            # resaving the now-invalid in-memory new session.
            key, user_id, nonce = expected
            row = identity.session_row(key)
            data = row.get_decoded() if row else {}
            failed = data.get(identity.SESSION_KEY) != user_id
            # Django admin is exempt from this whole pre-save check because
            # it relies on SessionMiddleware.save. API/OAuth save explicitly.
            failed = failed or data.get(identity.NONCE) != nonce
        if failed:
            # Empty/auth-less is deliberate: even SESSION_SAVE_EVERY_REQUEST
            # must not resave failed Python state after database rollback. The
            # browser keeps its old cookies; the outer transaction restores DB.
            request.session = SessionStore()
            request.session._session_cache = {}
            request.user = AnonymousUser()
            request._cached_user = request.user
            request._identity_issue_cookie = None
            request._identity_auth_failed = True
        return response

import hashlib
import json
import re
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.core.cache import caches
from django.core.cache.backends.base import InvalidCacheBackendError
from django.views.decorators.debug import sensitive_variables
from redis.exceptions import RedisError

from apps.wecom.credentials import CredentialError, decrypt_secret
from .message_cards import build_text_notice_card


class WeComError(Exception):
    def __init__(self, code, message, status=502):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class WeComSendUncertain(WeComError):
    def __init__(self):
        super().__init__("SEND_UNCERTAIN", "发送结果待核对，请先查看企业微信，勿重复发送。")


ERROR_MESSAGES = {
    "CONFIGURATION_ERROR": "企业微信应用配置不可用，请联系管理员检查配置。",
    "MEMBER_REJECTED": "无法确认有效的企业微信成员身份，请联系管理员。",
    "UPSTREAM_UNAVAILABLE": "企业微信服务暂时不可用，请稍后重新进入应用。",
}
# 仅映射官方错误码，第三方 errmsg 可能包含凭据，绝不能直接展示。
# https://developer.work.weixin.qq.com/document/path/90313
UPSTREAM_ERRORS = {
    40001: ("CONFIGURATION_ERROR", "企业微信应用 Secret 无效，请管理员重新核对并保存。"),
    40091: ("CONFIGURATION_ERROR", "企业微信应用 Secret 与企业不匹配，请管理员核对。"),
    40013: ("CONFIGURATION_ERROR", "企业微信 CorpID 无效，请管理员核对企业 ID。"),
    40056: ("CONFIGURATION_ERROR", "企业微信 AgentID 无效，请管理员核对应用 ID。"),
    60020: ("CONFIGURATION_ERROR", "服务器出口 IP 不在企业微信应用可信 IP 中，请管理员配置后重试。"),
    50001: ("CONFIGURATION_ERROR", "回调地址未登记为企业微信应用可信域名，请管理员检查域名配置。"),
    48001: ("CONFIGURATION_ERROR", "企业微信应用未获接口功能权限，请管理员检查授权。"),
    48002: ("CONFIGURATION_ERROR", "企业微信应用没有调用该接口的权限，请管理员检查授权。"),
    48004: ("CONFIGURATION_ERROR", "企业微信应用授权关系无效，请管理员检查授权。"),
    48006: ("CONFIGURATION_ERROR", "企业微信应用接口权限已被收回，请管理员重新启用。"),
    50003: ("CONFIGURATION_ERROR", "企业微信应用已禁用，请管理员启用后重试。"),
    50006: ("CONFIGURATION_ERROR", "企业微信系统应用已禁用，请管理员检查。"),
    60031: ("CONFIGURATION_ERROR", "企业微信应用已禁止调用接口，请管理员检查。"),
    301002: ("CONFIGURATION_ERROR", "当前凭据无权访问指定企业微信应用，请管理员核对 Secret 与 AgentID。"),
    40029: ("MEMBER_REJECTED", "企业微信登录授权已失效，请从工作台重新进入。"),
    42003: ("MEMBER_REJECTED", "企业微信登录授权已过期，请从工作台重新进入。"),
    50002: ("MEMBER_REJECTED", "成员不在企业微信应用权限范围内，请联系管理员。"),
    60011: ("MEMBER_REJECTED", "当前应用无权读取该成员，请管理员检查应用可见范围。"),
    60021: ("MEMBER_REJECTED", "成员不在企业微信应用可见范围内，请联系管理员。"),
    60030: ("MEMBER_REJECTED", "请求超出企业微信应用可见范围，请联系管理员。"),
    60111: ("MEMBER_REJECTED", "企业微信成员不存在，请管理员核对成员账号。"),
    60112: ("MEMBER_REJECTED", "企业微信成员资料不符合要求，请管理员核对。"),
}
CACHE_ERRORS = (InvalidCacheBackendError, RedisError, OSError)


def _error(code="UPSTREAM_UNAVAILABLE", message=None):
    return WeComError(code, message or ERROR_MESSAGES[code], 403 if code == "MEMBER_REJECTED" else 502)


@sensitive_variables()
def _check_result(result):
    if result["errcode"] != 0:
        raise _error(*UPSTREAM_ERRORS.get(result["errcode"], ("UPSTREAM_UNAVAILABLE",)))


def _valid_text(value, max_bytes):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return False
    return len(encoded) <= max_bytes and not any(ord(character) < 32 for character in value)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 查询参数带有凭据，任何重定向都不得继续发送。
        return None


class WeComClient:
    API_BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin/"
    TIMEOUT_SECONDS = 8
    MAX_RESPONSE_BYTES = 1024 * 1024

    def __init__(self, config):
        self.corp_id = config.corp_id
        agent_id = config.agent_id
        # 与配置字段的 30 位正整数契约一致，长度检查必须在 int 转换前。
        if (
            isinstance(agent_id, str)
            and 1 <= len(agent_id) <= 30
            and agent_id.isascii()
            and agent_id.isdecimal()
            and agent_id[0] != "0"
        ):
            self.agent_id = int(agent_id)
        elif type(agent_id) is int and 0 < agent_id < 10 ** 30:
            self.agent_id = agent_id
        else:
            raise _error("CONFIGURATION_ERROR")
        self.secret_ciphertext = config.secret_ciphertext
        if (
            not _valid_text(self.corp_id, 128)
            or not isinstance(self.secret_ciphertext, str)
            or not self.secret_ciphertext
        ):
            raise _error("CONFIGURATION_ERROR")
        cache_identity = json.dumps(
            [self.corp_id, self.agent_id, self.secret_ciphertext], separators=(",", ":"),
        ).encode()
        self.token_key = "wecom:access-token:" + hashlib.sha256(cache_identity).hexdigest()
        self.opener = build_opener(_NoRedirect())

    @sensitive_variables()
    def _request(self, endpoint, params):
        request = Request(self.API_BASE_URL + endpoint + "?" + urlencode(params), headers={"Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise _error()
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            error.close()
            raise _error() from None
        except (URLError, OSError, HTTPException):
            raise _error() from None
        if len(body) > self.MAX_RESPONSE_BYTES:
            raise _error()
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise _error() from None
        if not isinstance(result, dict) or type(result.get("errcode")) is not int:
            raise _error()
        return result

    @sensitive_variables()
    def _access_token(self, rejected_token=None):
        try:
            cache = caches["wecom"]
            token = cache.get(self.token_key)
        except CACHE_ERRORS:
            raise _error() from None
        if _valid_text(token, 4096) and token != rejected_token:
            return token
        try:
            secret = decrypt_secret(self.secret_ciphertext)
        except CredentialError:
            raise _error("CONFIGURATION_ERROR") from None
        if not _valid_text(secret, 4096):
            raise _error("CONFIGURATION_ERROR")
        result = self._request("gettoken", {"corpid": self.corp_id, "corpsecret": secret})
        _check_result(result)
        token = result.get("access_token")
        expires_in = result.get("expires_in")
        if not _valid_text(token, 4096) or type(expires_in) is not int or not 1 < expires_in <= 86400:
            raise _error()
        # 留出传输和服务器时钟误差；短有效期仍按其实际长度提前失效。
        ttl = expires_in - min(60, max(1, expires_in // 10))
        try:
            cache.set(self.token_key, token, timeout=ttl)
        except CACHE_ERRORS:
            raise _error() from None
        return token

    @sensitive_variables()
    def _authenticated_get(self, endpoint, params):
        token = self._access_token()
        result = self._request(endpoint, {**params, "access_token": token})
        # 只有官方明确认定 token 无效时重发一次；网络失败不重放 OAuth code。
        if result["errcode"] in (40014, 42001):
            token = self._access_token(rejected_token=token)
            result = self._request(endpoint, {**params, "access_token": token})
        return result

    @sensitive_variables()
    def get_identity(self, code):
        if not _valid_text(code, 512):
            raise _error("MEMBER_REJECTED")
        result = self._authenticated_get("auth/getuserinfo", {"code": code})
        _check_result(result)
        user_id = result.get("userid")
        corp_id = result.get("corpid", self.corp_id)
        if not _valid_text(user_id, 64) or corp_id != self.corp_id or result.get("openid"):
            raise _error("MEMBER_REJECTED")
        return {"userid": user_id, "corpid": self.corp_id}

    @sensitive_variables()
    def get_member(self, user_id):
        if not _valid_text(user_id, 64):
            raise _error("MEMBER_REJECTED")
        result = self._authenticated_get("user/get", {"userid": user_id})
        _check_result(result)
        official_user_id = result.get("userid")
        name = result.get("name")
        status = result.get("status")
        if (
            not _valid_text(official_user_id, 64)
            or official_user_id.lower() != user_id.lower()
            or not _valid_text(name, 256)
            or type(status) is not int
            or status != 1
        ):
            raise _error("MEMBER_REJECTED")
        return {"userid": official_user_id, "name": name.strip(), "status": status}

    @sensitive_variables()
    def check_connection(self):
        result = self._authenticated_get("agent/get", {"agentid": self.agent_id})
        _check_result(result)
        if type(result.get("agentid")) is not int or result["agentid"] != self.agent_id:
            raise _error("CONFIGURATION_ERROR")
        name = result.get("name", "")
        if not isinstance(name, str):
            raise _error()
        return {"agentid": self.agent_id, "name": name}

    @sensitive_variables()
    def _post_message(self, token, payload):
        request = Request(self.API_BASE_URL + "message/send?" + urlencode({"access_token": token}),
                          data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                          headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=self.TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise WeComSendUncertain()
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            error.close()
            raise WeComSendUncertain() from None
        except (URLError, OSError, HTTPException):
            # POST 发出后无法由网络异常判断对方是否已经接受，绝不自动重发。
            raise WeComSendUncertain() from None
        if len(body) > self.MAX_RESPONSE_BYTES:
            raise WeComSendUncertain()
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise WeComSendUncertain() from None
        if not isinstance(result, dict) or type(result.get("errcode")) is not int:
            raise WeComSendUncertain()
        return result

    @sensitive_variables()
    def send_text(self, user_id, content):
        valid_recipient = isinstance(user_id, str) and re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", user_id) and user_id.lower() != "@all"
        try:
            valid_content = (isinstance(content, str) and content.strip() and len(content.encode("utf-8")) <= 2048
                             and not any(ord(char) < 32 and char not in "\n\r\t" for char in content))
        except UnicodeError:
            valid_content = False
        if not valid_recipient or not valid_content:
            raise WeComError("MESSAGE_REJECTED", "接收人或消息正文无效。", 400)
        payload = {"touser": user_id, "msgtype": "text", "agentid": self.agent_id, "text": {"content": content},
                   "enable_duplicate_check": 1, "duplicate_check_interval": 1800}
        return self._send_message(user_id, payload)

    @sensitive_variables()
    def send_text_notice(self, user_id, *, title, body, url, preview=True):
        if (not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", user_id)
                or user_id.lower() == "@all"):
            raise WeComError("MESSAGE_REJECTED", "接收人无效。", 400)
        try:
            card = build_text_notice_card(title, body, url, preview=preview)
        except ValueError as exc:
            raise WeComError("MESSAGE_REJECTED", str(exc), 400) from None
        payload = {"touser": user_id, "msgtype": "template_card", "agentid": self.agent_id,
                   "template_card": card, "enable_duplicate_check": 1, "duplicate_check_interval": 1800}
        return self._send_message(user_id, payload)

    @sensitive_variables()
    def _send_message(self, user_id, payload):
        token = self._access_token()
        result = self._post_message(token, payload)
        if result["errcode"] in (40014, 42001):
            # 官方明确拒绝旧 token 才可重试一次；同一正文及接收人保持不变。
            token = self._access_token(rejected_token=token)
            result = self._post_message(token, payload)
        if result["errcode"] != 0:
            code, message = UPSTREAM_ERRORS.get(result["errcode"], ("MESSAGE_REJECTED", "企业微信明确拒绝了消息。"))
            if result["errcode"] == 81013 or code == "MEMBER_REJECTED":
                code, message = "RECIPIENT_REJECTED", "接收人无效、不在应用可见范围内或缺少接口许可。"
            raise WeComError(code, message)
        for field in ("invaliduser", "unlicenseduser", "invalidparty", "invalidtag"):
            invalid = result.get(field, "")
            if not isinstance(invalid, str):
                raise WeComSendUncertain()
            if invalid:
                if field in ("invaliduser", "unlicenseduser") and user_id.lower() in invalid.lower().split("|"):
                    raise WeComError("RECIPIENT_REJECTED", "接收人无效、不在应用可见范围内或缺少接口许可。")
                raise WeComSendUncertain()
        msgid = result.get("msgid")
        if not _valid_text(msgid, 512):
            raise WeComSendUncertain()
        return {"msgid": msgid}

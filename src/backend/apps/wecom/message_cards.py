from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def build_preview_card(title, body, url):
    return build_text_notice_card(title, body, url, preview=True)


def build_text_notice_card(title, body, url, *, preview):
    """沿用通知文本边界，保留换行；36/160是展示建议，不作为接口硬限制。"""
    for value, limit, label in ((title, 200, "标题"), (body, 2048, "正文")):
        try:
            valid = (isinstance(value, str) and value.strip() and len(value) <= limit
                     and not any(ord(char) < 32 and char not in "\n\r\t" for char in value))
            if valid:
                value.encode("utf-8")
        except UnicodeError:
            valid = False
        if not valid:
            raise ValueError(f"卡片的{label}请填写有效文本，且不超过{limit}个字；原模板不会被截断。")
    if len(f"{title}\n\n{body}".encode("utf-8")) > 2048:
        raise ValueError("完整卡片内容不能超过2048个UTF-8字节；原模板不会被截断。")
    try:
        URLValidator(schemes=["https"])(url)
        parsed = urlsplit(url)
        if (parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.path not in ("", "/") or parsed.fragment):
            raise ValueError
        if preview:
            if parsed.query:
                raise ValueError
        else:
            params = parse_qs(parsed.query, strict_parsing=True)
            if set(params) != {"notification"} or len(params["notification"]) != 1:
                raise ValueError
            if str(UUID(params["notification"][0])) != params["notification"][0]:
                raise ValueError
    except (ValidationError, ValueError, TypeError):
        raise ValueError("卡片需要有效的 HTTPS ERP 地址与通知详情标识，请先核对企业微信应用配置。") from None
    return {
        "card_type": "text_notice",
        "source": {"desc": "HAIQU ERP · 测试" if preview else "HAIQU ERP"},
        "main_title": {"title": title, "desc": "预览试发 · 示例内容" if preview else "业务通知"},
        "sub_title_text": body,
        "jump_list": [{"type": 1, "title": "查看详情", "url": url}],
        "card_action": {"type": 1, "url": url},
    }

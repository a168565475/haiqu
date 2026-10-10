import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

from rest_framework import serializers


MAX_RICH_TEXT_CHARACTERS = 5000
MAX_RICH_TEXT_HTML_LENGTH = 50000

ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "img",
    "input",
    "label",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "s",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
VOID_TAGS = {"br", "hr", "img", "input"}
TAG_ALIASES = {"b": "strong", "i": "em", "strike": "s"}
DISCARDED_CONTENT_TAGS = {"iframe", "object", "script", "style"}
ALLOWED_FONT_SIZES = {"12px", "14px", "16px", "18px", "20px", "24px"}
ALLOWED_TEXT_ALIGNS = {"left", "center", "right", "justify"}
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")
INQUIRY_IMAGE_PATH_PATTERN = re.compile(
    r"^/api/v1/inquiries/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/images/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/$",
    re.IGNORECASE,
)


def _safe_link(value):
    link = (value or "").strip()
    if not link or any(ord(character) < 32 for character in link):
        return ""
    parsed = urlparse(link)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"} and parsed.netloc:
        return link
    if scheme == "mailto" and parsed.path:
        return link
    return ""


def _safe_color(value):
    color = (value or "").strip()
    return color if HEX_COLOR_PATTERN.fullmatch(color) else ""


def _safe_image_source(value):
    source = (value or "").strip()
    if not source or any(ord(character) < 32 for character in source):
        return ""
    return source if INQUIRY_IMAGE_PATH_PATTERN.fullmatch(source) else ""


def _safe_positive_integer(value, maximum=20):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    return str(number) if 1 <= number <= maximum else ""


def _safe_styles(tag, value):
    if not value:
        return ""

    safe_styles = []
    for declaration in value.split(";"):
        property_name, separator, property_value = declaration.partition(":")
        if not separator:
            continue
        property_name = property_name.strip().lower()
        property_value = property_value.strip().lower()
        if property_name in {"color", "background-color"} and _safe_color(property_value):
            safe_styles.append(f"{property_name}: {property_value}")
        elif (
            property_name == "font-size"
            and tag == "span"
            and property_value in ALLOWED_FONT_SIZES
        ):
            safe_styles.append(f"font-size: {property_value}")
        elif (
            property_name == "text-align"
            and tag in {"h1", "h2", "h3", "h4", "p", "td", "th"}
            and property_value in ALLOWED_TEXT_ALIGNS
        ):
            safe_styles.append(f"text-align: {property_value}")
    return "; ".join(safe_styles)


def _safe_attributes(tag, attrs):
    attributes = dict(attrs)
    safe_attributes = []

    if tag == "a":
        href = _safe_link(attributes.get("href"))
        if not href:
            return None
        safe_attributes.extend(
            [
                ("href", href),
                ("target", "_blank"),
                ("rel", "noopener noreferrer"),
            ]
        )
    elif tag == "img":
        source = _safe_image_source(attributes.get("src"))
        if not source:
            return None
        safe_attributes.append(("src", source))
        alt = (attributes.get("alt") or "").strip()
        if alt and not any(ord(character) < 32 for character in alt):
            safe_attributes.append(("alt", alt[:255]))
    elif tag == "input":
        if attributes.get("type", "").lower() != "checkbox":
            return None
        safe_attributes.append(("type", "checkbox"))
        if "checked" in attributes:
            safe_attributes.append(("checked", "checked"))
        safe_attributes.append(("disabled", "disabled"))
    elif tag in {"ul", "li"}:
        data_type = attributes.get("data-type")
        if data_type in {"taskList", "taskItem"}:
            safe_attributes.append(("data-type", data_type))
        if tag == "li" and attributes.get("data-checked") in {"true", "false"}:
            safe_attributes.append(("data-checked", attributes["data-checked"]))
    elif tag == "mark":
        color = _safe_color(attributes.get("data-color"))
        if color:
            safe_attributes.append(("data-color", color))
    elif tag in {"td", "th"}:
        for attribute_name in ("colspan", "rowspan"):
            safe_value = _safe_positive_integer(attributes.get(attribute_name))
            if safe_value:
                safe_attributes.append((attribute_name, safe_value))

    safe_style = _safe_styles(tag, attributes.get("style"))
    if safe_style:
        safe_attributes.append(("style", safe_style))
    return safe_attributes


class RichTextSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.open_tags = []
        self.discarded_depth = 0
        self.character_count = 0
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        source_tag = tag.lower()
        normalized = TAG_ALIASES.get(source_tag, source_tag)
        if normalized in DISCARDED_CONTENT_TAGS:
            self.discarded_depth += 1
            return
        if self.discarded_depth or normalized not in ALLOWED_TAGS:
            return

        safe_attributes = _safe_attributes(normalized, attrs)
        output_tag = normalized if safe_attributes is not None else None
        if output_tag:
            attribute_html = "".join(
                f' {name}="{escape(value, quote=True)}"'
                for name, value in safe_attributes
            )
            if output_tag in VOID_TAGS:
                self.output.append(f"<{output_tag}{attribute_html}>")
            else:
                self.output.append(f"<{output_tag}{attribute_html}>")
        if normalized not in VOID_TAGS:
            self.open_tags.append((normalized, output_tag))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        normalized = TAG_ALIASES.get(tag.lower(), tag.lower())
        if normalized not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        normalized = TAG_ALIASES.get(tag.lower(), tag.lower())
        if normalized in DISCARDED_CONTENT_TAGS:
            if self.discarded_depth:
                self.discarded_depth -= 1
            return
        if self.discarded_depth or normalized not in ALLOWED_TAGS or normalized in VOID_TAGS:
            return

        matching_index = next(
            (
                index
                for index in range(len(self.open_tags) - 1, -1, -1)
                if self.open_tags[index][0] == normalized
            ),
            None,
        )
        if matching_index is None:
            return
        while len(self.open_tags) > matching_index:
            _, output_tag = self.open_tags.pop()
            if output_tag:
                self.output.append(f"</{output_tag}>")

    def handle_data(self, data):
        if self.discarded_depth:
            return
        self.character_count += len(data)
        self.text_parts.append(data)
        self.output.append(escape(data))

    def sanitized_html(self):
        while self.open_tags:
            _, output_tag = self.open_tags.pop()
            if output_tag:
                self.output.append(f"</{output_tag}>")
        return "".join(self.output).strip()


def sanitize_rich_text(value, *, enforce_limits=True):
    raw_value = value or ""
    if enforce_limits and len(raw_value) > MAX_RICH_TEXT_HTML_LENGTH:
        raise serializers.ValidationError(
            f"沟通内容格式化后的数据不能超过 {MAX_RICH_TEXT_HTML_LENGTH} 个字符。"
        )
    sanitizer = RichTextSanitizer()
    sanitizer.feed(raw_value)
    sanitizer.close()
    if enforce_limits and sanitizer.character_count > MAX_RICH_TEXT_CHARACTERS:
        raise serializers.ValidationError(
            f"沟通内容不能超过 {MAX_RICH_TEXT_CHARACTERS} 个文字。"
        )
    return sanitizer.sanitized_html()


def rich_text_plain_text(value):
    """提取允许内容中的文字，用于必填项和可见文字长度校验。"""
    sanitizer = RichTextSanitizer()
    sanitizer.feed(value or "")
    sanitizer.close()
    return "".join(sanitizer.text_parts)

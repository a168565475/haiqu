import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request

from .errors import AiProviderRequestFailed, AiOutputInvalid
from .mapping import erp_mapping_instructions, normalize_erp_fields
from .field_coverage import complete_tube_field_coverage
from .date_fields import cell_date, normalize_date_fields
from .recognition_rules import recognition_metadata, rule_instructions, source_rule_context
from .schema import OUTPUT_SCHEMA
from .validation import validate_result


SYSTEM_PROMPT = """你是海趣 ERP 的生产任务资料识别器。输入只有表格文字 JSON，不包含图片。
只提取输入中明确存在的事实；不要猜测 ERP 主档 ID、员工、单位或日期。
每个字段必须给出来源 source_ids，只能引用输入中的短 source_id；确实未填时status=MISSING，无法读取时UNREADABLE，存在矛盾时CONFLICT。仅白名单已确认缺失默认可用DEFAULTED，注明规则及已读上下文；不能把未读当未填。
保留原文和原计量口径，不遗漏用料行。issues 集中记录缺失、冲突和无法判断的内容。
标记 image_omitted 的内容未发送，不得推测图片内容；需要时由用户在 ERP 手动上传。""" + "\n\n" + erp_mapping_instructions() + "\n\n" + rule_instructions()

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STREAM_BYTES = 32 * 1024 * 1024
RECOGNITION_TIMEOUT_SECONDS = 600
IMAGE_FORMULA = re.compile(r"(?:^|[^A-Z0-9_])(?:(?:_xlfn|_xlws)\.)*(?:DISPIMG|IMAGE)\s*\(", re.IGNORECASE)


def _prepare_model_source(source):
    """只投影业务文字，短来源编号在返回结果后还原，不改动原始来源记录。"""

    short_ids, source_ids = {}, {}

    def project(item, fields):
        result = {key: item[key] for key in fields if item.get(key) is not None}
        source_id = item.get("source_id")
        if source_id:
            if source_id not in source.get("source_index", {}):
                raise AiProviderRequestFailed("OPENAI_INPUT_SOURCE_INVALID")
            if source_id not in short_ids:
                alias = f"s{len(short_ids) + 1}"
                short_ids[source_id] = alias
                source_ids[alias] = source_id
            result["source_id"] = short_ids[source_id]
        # 图片专用公式和 data URI 也可能出现在单元格文本中，不能以 input_text 绕过图片外发边界。
        image_formula = any(IMAGE_FORMULA.search(str(item.get(key) or "")) for key in ("formula", "text"))
        image_omitted = False

        def text_only(value):
            nonlocal image_omitted
            if isinstance(value, str) and "data:image/" in value.lower():
                image_omitted = True
                return "[图片内容未发送]"
            if isinstance(value, dict):
                return {key: text_only(child) for key, child in value.items()}
            if isinstance(value, list):
                return [text_only(child) for child in value]
            return value

        result = text_only(result)
        if image_formula:
            for key in ("text", "formula", "cache"):
                if key in result:
                    result[key] = "[图片内容未发送]"
            image_omitted = True
        if image_omitted:
            result["image_omitted"] = True
        normalized_date = cell_date(item, source)
        if normalized_date:
            result["normalized_date"] = normalized_date
        return result

    sheets = []
    for sheet in source.get("sheets", []):
        sheets.append({
            **project(sheet, ("name", "state", "dimension")),
            "merged_cells": sheet.get("merged_cells", []),
            "comments": [
                project(comment, ("ref", "text"))
                for comment in sheet.get("comments", [])
            ],
            "cells": [
                project(cell, ("ref", "type", "text", "formula", "cache", "formula_attributes", "num_format_id", "num_format"))
                for cell in sheet.get("cells", [])
            ],
        })
    return {
        "schema_version": source.get("schema_version"),
        "original_name": source.get("original_name"),
        "format": source.get("format", "xlsx"),
        "date1904": source.get("date1904", "0"),
        "sheets": sheets,
        "limitations": [
            *source.get("limitations", []),
            "本次仅识别表格文字，不发送或识别嵌入图片；图片需在 ERP 中手动上传。",
        ],
    }, source_ids


def _model_source(source):
    return _prepare_model_source(source)[0]


def _restore_source_ids(value, source_ids):
    if isinstance(value, list):
        return [_restore_source_ids(item, source_ids) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "source_ids":
                if not isinstance(item, list) or any(not isinstance(ref, str) or ref not in source_ids for ref in item):
                    raise AiOutputInvalid("OPENAI_OUTPUT_SOURCE_INVALID")
                result[key] = [source_ids[ref] for ref in item]
            else:
                result[key] = _restore_source_ids(item, source_ids)
        return result
    return value


def _response_text(payload):
    if isinstance(payload, dict):
        if payload.get("status") == "failed":
            raise AiProviderRequestFailed("OPENAI_SERVER_ERROR")
        if payload.get("status") != "completed":
            raise AiOutputInvalid("OPENAI_RESPONSE_INCOMPLETE")
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, list):
        raise AiOutputInvalid("OPENAI_RESPONSE_SHAPE_INVALID")
    chunks = []
    for item in output:
        for content in item.get("content", []) if isinstance(item, dict) else []:
            if isinstance(content, dict) and content.get("type") == "refusal":
                raise AiOutputInvalid("OPENAI_RESPONSE_REFUSED")
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    if not chunks:
        raise AiOutputInvalid("OPENAI_RESPONSE_TEXT_MISSING")
    try:
        return json.loads("".join(chunks))
    except (TypeError, ValueError) as error:
        raise AiOutputInvalid("OPENAI_RESPONSE_JSON_INVALID") from error


def _decode_json(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeError) as error:
        raise AiOutputInvalid("OPENAI_RESPONSE_JSON_INVALID") from error


def _read_response(response, deadline):
    def read(size, *, line=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AiProviderRequestFailed("OPENAI_TIMEOUT")
        # urllib 的 socket 超时默认按每次读重置；后续读取只使用总期限剩余的时间。
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        data = response.readline(size) if line else response.read(size)
        if time.monotonic() >= deadline:
            raise AiProviderRequestFailed("OPENAI_TIMEOUT")
        return data

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "text/event-stream":
        data = read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise AiProviderRequestFailed("OPENAI_RESPONSE_TOO_LARGE")
        return _decode_json(data)

    received = 0
    event_bytes = 0
    event_type = ""
    data_lines = []
    while True:
        line = read(min(MAX_RESPONSE_BYTES - event_bytes, MAX_STREAM_BYTES - received) + 1, line=True)
        received += len(line)
        event_bytes += len(line)
        if received > MAX_STREAM_BYTES or event_bytes > MAX_RESPONSE_BYTES:
            raise AiProviderRequestFailed("OPENAI_RESPONSE_TOO_LARGE")
        if not line:
            raise AiOutputInvalid("OPENAI_RESPONSE_INTERRUPTED")
        try:
            line = line.decode("utf-8").rstrip("\r\n")
        except UnicodeError as error:
            raise AiOutputInvalid("OPENAI_RESPONSE_JSON_INVALID") from error
        if line:
            field, separator, value = line.partition(":")
            if separator and field in {"event", "data"}:
                value = value.removeprefix(" ")
                if field == "event":
                    event_type = value
                else:
                    data_lines.append(value)
            continue
        if not data_lines:
            event_type = ""
            event_bytes = 0
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            raise AiOutputInvalid("OPENAI_RESPONSE_INTERRUPTED")
        event = _decode_json(data)
        if not isinstance(event, dict):
            raise AiOutputInvalid("OPENAI_RESPONSE_SHAPE_INVALID")
        kind = event.get("type") or event_type
        if event_type and kind != event_type:
            raise AiOutputInvalid("OPENAI_RESPONSE_SHAPE_INVALID")
        if kind in {"error", "response.failed"}:
            raise AiProviderRequestFailed("OPENAI_SERVER_ERROR")
        if kind == "response.incomplete":
            incomplete = event.get("response")
            details = incomplete.get("incomplete_details") if isinstance(incomplete, dict) else None
            if isinstance(details, dict) and details.get("reason") == "max_output_tokens":
                raise AiOutputInvalid("OPENAI_OUTPUT_LIMIT")
            raise AiOutputInvalid("OPENAI_RESPONSE_INCOMPLETE")
        if kind in {"response.refusal.delta", "response.refusal.done"}:
            raise AiOutputInvalid("OPENAI_RESPONSE_REFUSED")
        if kind == "response.completed":
            payload = event.get("response")
            if not isinstance(payload, dict) or payload.get("status") != "completed":
                raise AiOutputInvalid("OPENAI_RESPONSE_INCOMPLETE")
            return payload
        # 增量文字不能作为结果交付；只有 completed 的完整 response 才进入原有校验。
        event_type = ""
        data_lines = []
        event_bytes = 0


def set_reasoning_effort(body, effort, *, gpt6_default):
    if effort == "auto":
        if not body["model"].startswith("gpt-6"):
            return
        effort = gpt6_default
    body["reasoning"] = {"effort": effort}


def recognize(*, credentials, controlled, timeout_seconds=RECOGNITION_TIMEOUT_SECONDS, confirmed_source_rules=()):
    api_key = credentials.get("api_key")
    model = credentials.get("model") or "gpt-6-astra"
    if not isinstance(api_key, str) or not api_key.strip():
        raise AiProviderRequestFailed("OPENAI_KEY_EMPTY")
    source, source_ids = _prepare_model_source(controlled["source"])
    scoped_rules = source_rule_context(controlled["source"], confirmed_source_rules)
    if scoped_rules:
        source["confirmed_source_rules"] = scoped_rules
        source["limitations"].append("confirmed_source_rules由宿主按文件指纹提供，仅适用于其中任务号对应的真实任务；不修改原表，原值、采用值和规则编号须在note保留。")
    input_content = [{"type": "input_text", "text": json.dumps(source, ensure_ascii=False, separators=(",", ":"))}]
    body = {
        "model": model,
        "stream": True,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": input_content},
        ],
        "text": {"format": {"type": "json_schema", "name": "production_task_import", "strict": True, "schema": OUTPUT_SCHEMA}},
    }
    set_reasoning_effort(body, credentials.get("document_reasoning_effort", "auto"), gpt6_default="xhigh")
    deadline = time.monotonic() + timeout_seconds
    payload = request_response(credentials, body, deadline=deadline)
    result = _restore_source_ids(_response_text(payload), source_ids)
    result = normalize_date_fields(normalize_erp_fields(result), controlled["source"])
    result = validate_result(result, controlled["source"])
    result = validate_result(complete_tube_field_coverage(result, controlled["source"]), controlled["source"])
    result["recognition_meta"] = recognition_metadata(scoped_rules)
    return result, model


def request_response(credentials, body, *, deadline):
    """识别和ERP查询共用传输；多轮请求共享调用方给出的总期限。"""
    api_key = credentials.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise AiProviderRequestFailed("OPENAI_KEY_EMPTY")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AiProviderRequestFailed("OPENAI_TIMEOUT")
    base_url = (credentials.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/responses", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST",
    )
    phase = "connect"
    try:
        with urllib.request.urlopen(request, timeout=remaining) as response:
            phase = "read"
            if response.status < 200 or response.status >= 300:
                raise AiProviderRequestFailed("OPENAI_HTTP_ERROR")
            return _read_response(response, deadline)
    except AiProviderRequestFailed:
        raise
    except urllib.error.HTTPError as error:
        code = {
            400: "OPENAI_BAD_REQUEST", 401: "OPENAI_AUTH_FAILED", 403: "OPENAI_ACCESS_DENIED",
            404: "OPENAI_MODEL_NOT_FOUND", 429: "OPENAI_RATE_LIMITED",
        }.get(error.code, "OPENAI_SERVER_ERROR" if error.code >= 500 else "OPENAI_HTTP_ERROR")
        raise AiProviderRequestFailed(code) from error
    except TimeoutError as error:
        raise AiProviderRequestFailed("OPENAI_TIMEOUT") from error
    except urllib.error.URLError as error:
        logging.getLogger(__name__).warning("OpenAI transport failed: phase=%s type=%s reason_type=%s errno=%s",
                                           phase, type(error).__name__, type(error.reason).__name__, getattr(error.reason, "errno", None))
        code = "OPENAI_TIMEOUT" if isinstance(error.reason, TimeoutError) else "OPENAI_NETWORK_ERROR"
        raise AiProviderRequestFailed(code) from error
    except (http.client.HTTPException, ConnectionError, OSError) as error:
        logging.getLogger(__name__).warning("OpenAI transport failed: phase=%s type=%s errno=%s library=%s reason=%s",
                                           phase, type(error).__name__, getattr(error, "errno", None),
                                           getattr(error, "library", None), getattr(error, "reason", None))
        raise AiProviderRequestFailed("OPENAI_NETWORK_ERROR") from error

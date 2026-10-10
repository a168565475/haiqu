import json
from functools import lru_cache
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


SAMPLING_DETAIL_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "sampling_detail_template.json"


@lru_cache(maxsize=1)
def load_sampling_detail_template():
    try:
        document = json.loads(SAMPLING_DETAIL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImproperlyConfigured("打样信息明细配置文件无法读取。") from exc

    rows = document.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ImproperlyConfigured("打样信息明细配置必须包含 1 到 100 行。")

    normalized = []
    seen_keys = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ImproperlyConfigured(f"打样信息明细配置第 {index} 行格式不正确。")
        key = str(row.get("key", "")).strip()
        detail_type = str(row.get("type", "")).strip()
        category = str(row.get("category", "")).strip()
        if not key or key in seen_keys or len(key) > 64:
            raise ImproperlyConfigured(f"打样信息明细配置第 {index} 行 key 为空、重复或过长。")
        if not detail_type or len(detail_type) > 100 or len(category) > 100:
            raise ImproperlyConfigured(f"打样信息明细配置第 {index} 行类型或类别不正确。")
        seen_keys.add(key)
        normalized.append({"key": key, "type": detail_type, "category": category})
    return tuple(normalized)

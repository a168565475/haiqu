"""读取本机已确认的来源特例，仅把同一文件版本的记录交给识别器。"""

import json
import re
from pathlib import Path

from django.conf import settings

from .errors import AiProductionImportError


def confirmed_source_rules(source):
    path = Path(settings.BASE_DIR) / "private/ai_import_source_rules.json"
    if not path.is_file():
        return []
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("来源规则文件过大")
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("来源规则必须是数组")
        selected = []
        texts = [str(cell.get("text", "")) for sheet in source.get("sheets", [])
                 for cell in sheet.get("cells", [])]
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("来源规则项无效")
            if entry.get("source_sha256") != source.get("source_sha256"):
                continue
            task_number = entry.get("task_number")
            if not isinstance(task_number, str) or not task_number:
                raise ValueError("来源任务身份缺失")
            # 相同字节版本还须能在正文找到任务身份；文件名不作为身份凭据。
            pattern = re.compile(r"(?<![A-Za-z0-9-])" + re.escape(task_number) + r"(?![A-Za-z0-9-])")
            if any(pattern.search(text) for text in texts):
                selected.append(entry)
        return selected
    except (OSError, UnicodeError, ValueError) as error:
        raise AiProductionImportError("AI_SOURCE_RULES_INVALID", "已确认来源规则读取失败，请检查本机规则文件。") from error

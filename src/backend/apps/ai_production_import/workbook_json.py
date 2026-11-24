import hashlib
import io
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import zipfile

from .errors import AiProductionImportError


MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_CELLS = 100_000
MAX_SHEETS = 50
MAX_JSON_BYTES = 2 * 1024 * 1024


def _source_id(sha256: str, sheet: str, ref: str) -> str:
    token = json.dumps([sha256, sheet, ref], ensure_ascii=False, separators=(",", ":"))
    return "src_" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _read_upload(uploaded_file):
    name = str(getattr(uploaded_file, "name", "") or "").strip()
    suffix = Path(name).suffix.lower()
    if name.startswith("~$") or suffix not in {".xlsx", ".xls"}:
        raise AiProductionImportError("UNSUPPORTED_FILE", "只支持 .xlsx 或 .xls 表格文件。")
    data = uploaded_file.read()
    if not isinstance(data, bytes) or not data or len(data) > MAX_FILE_BYTES:
        raise AiProductionImportError("INPUT_SIZE_LIMIT", "表格为空或超过 25 MiB 限制。")
    return name, suffix, data


def _xlsx_manifest(name, data):
    # 复用现有受控 XLSX 包解析：拒绝路径穿越、宏、外链读取和 ZIP 炸弹。
    from apps.production_task_imports.preprocessing import ManifestError, build_manifest

    with NamedTemporaryFile(suffix=".xlsx") as temp:
        temp.write(data)
        temp.flush()
        try:
            manifest, _, members = build_manifest(temp.name)
        except ManifestError as error:
            raise AiProductionImportError(str(error), "XLSX 文件未通过安全结构检查。") from error
    manifest["original_name"] = name
    image_parts = {
        item["id"]: ("image/png" if item["format"] == "PNG" else "image/jpeg", members[item["part"]])
        for item in manifest.get("images", [])
        if item.get("part") in members
    }
    return manifest, image_parts


def _xls_manifest(name, data):
    try:
        import xlrd
    except ImportError as error:
        raise AiProductionImportError("XLS_READER_UNAVAILABLE", "当前运行环境未安装 XLS 解析依赖。") from error
    try:
        workbook = xlrd.open_workbook(file_contents=data, on_demand=False, formatting_info=False)
    except Exception as error:  # xlrd 会抛多种格式异常；不把不可信文件详情返回给前端。
        raise AiProductionImportError("XLS_PARSE_FAILED", "XLS 文件无法读取。") from error
    if workbook.nsheets > MAX_SHEETS:
        raise AiProductionImportError("SHEET_COUNT_LIMIT", "工作表数量超过限制。")
    sha256 = hashlib.sha256(data).hexdigest()
    sheets, source_index, cell_count = [], {}, 0
    for sheet in workbook.sheets():
        cells = []
        for row_index in range(sheet.nrows):
            for col_index in range(sheet.ncols):
                cell = sheet.cell(row_index, col_index)
                if cell.value in (None, ""):
                    continue
                cell_count += 1
                if cell_count > MAX_CELLS:
                    raise AiProductionImportError("CELL_COUNT_LIMIT", "非空单元格数量超过限制。")
                ref = f"{_column_name(col_index + 1)}{row_index + 1}"
                source_id = _source_id(sha256, sheet.name, ref)
                item = {
                    "ref": ref,
                    "type": cell.ctype,
                    "text": cell.value,
                    "formula": None,
                    "cache": None,
                    "source_id": source_id,
                }
                cells.append(item)
                source_index[source_id] = {"kind": "cell", "sheet": sheet.name, "ref": ref}
        sheets.append({
            "name": sheet.name,
            "state": "visible",
            "dimension": f"A1:{_column_name(sheet.ncols)}{sheet.nrows}" if sheet.nrows and sheet.ncols else None,
            "merged_cells": [],
            "cells": cells,
            "pictures": [],
            "comments": [],
        })
    result = {
        "schema_version": "ai-production-import-source-v1",
        "source_sha256": sha256,
        "source_bytes": len(data),
        "original_name": name,
        "format": "xls",
        "untrusted_source": True,
        "formulas_evaluated": False,
        "scan_status": "CLEAN",
        "sheets": sheets,
        "images": [],
        "cell_images": {},
        "external_relationships": [],
        "source_index": source_index,
        "limitations": ["BIFF8 原始公式文本和图片对象未由 xlrd 提供；数值按缓存读取。"],
    }
    return result, {}


def _column_name(number):
    value = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value or "A"


def build_controlled_json(uploaded_file):
    name, suffix, data = _read_upload(uploaded_file)
    _scan_bytes(data, suffix)
    manifest, image_parts = _xlsx_manifest(name, data) if suffix == ".xlsx" else _xls_manifest(name, data)
    encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise AiProductionImportError("JSON_SIZE_LIMIT", "表格转 JSON 后超过 2 MiB 限制。")
    return {
        "original_name": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "format": suffix[1:],
        "source": manifest,
        "image_parts": image_parts,
        "raw_bytes": data,
    }


def _scan_bytes(data, suffix):
    """在解析和外发前执行项目统一的 ClamAV 文件扫描。"""
    from django.conf import settings
    from apps.imports.security import InfectedFile, ScannerUnavailable, scan_upload

    if not settings.FILE_VIRUS_SCAN_ENABLED:
        raise AiProductionImportError("SCAN_UNAVAILABLE", "当前文件扫描未启用，不能进行 AI 识别。")
    try:
        with NamedTemporaryFile(suffix=suffix) as temp:
            temp.write(data)
            temp.flush()
            # scan_upload 的扫描器按 Path 读取临时文件，不能传入字符串路径。
            status, _ = scan_upload(Path(temp.name))
    except InfectedFile as error:
        raise AiProductionImportError("SCAN_INFECTED", "上传文件未通过病毒扫描。") from error
    except ScannerUnavailable as error:
        raise AiProductionImportError("SCAN_UNAVAILABLE", "文件扫描服务暂不可用。") from error
    except OSError as error:
        raise AiProductionImportError("SCAN_FAILED", "文件扫描失败。") from error
    if status != "CLEAN":
        raise AiProductionImportError("SCAN_UNAVAILABLE", "文件扫描未返回可用结果。")

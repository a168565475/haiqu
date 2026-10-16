"""独立读取原始Excel与真实API逐行核对；不使用导入器的映射函数。"""
import argparse
import hashlib
import json
import traceback
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import openpyxl


def verify(source_path, state_path, base):
    source = Path(source_path)
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError("目标必须为不含凭据和路径的HTTP(S)源地址")
    state = json.loads(Path(state_path).read_text(encoding="utf-8-sig"))
    cookies = "; ".join(f"{c['name']}={c['value']}" for c in state["cookies"] if c["name"] in {"sessionid", "csrftoken"} and parsed.hostname == c["domain"].lstrip("."))
    if not cookies:
        raise ValueError("没有属于指定目标的Session Cookie")
    reads = 0

    def get(route):
        nonlocal reads
        with urlopen(Request(base.rstrip("/") + route, headers={"Cookie": cookies}), timeout=30) as response:
            reads += 1
            return json.load(response), response.headers.get("ETag")

    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=False)
    try:
        sheet = workbook["产品信息"]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)
        if tuple(header) != ("类型", "产品编码", "类别", "品名", "规格", "单位", "货号", "仓库号", "仓库名称", "规模"):
            raise ValueError("源表表头变化")
        expected = {i: dict(zip(header, row)) for i, row in enumerate(rows, start=2) if any(value is not None for value in row)}
    finally:
        workbook.close()
    actual, total, page_number = [], None, 1
    while total is None or len(actual) < total:
        body, _ = get("/api/v1/product-catalog/?" + urlencode({"page": page_number, "page_size": 100}))
        if total is not None and body["meta"]["total"] != total:
            raise ValueError("核验期间产品总数变化，须重新核验")
        total = body["meta"]["total"]
        if not body["data"] and len(actual) < total:
            raise ValueError("分页提前返回空数据")
        actual.extend(body["data"])
        page_number += 1
    mismatches, seen, digests = [], {}, []
    for summary in actual:
        response, etag = get(f"/api/v1/product-catalog/{summary['id']}/")
        record = response["data"]
        trace = record.get("source")
        if not trace or trace["filename"] != source.name:
            continue
        row_number = trace["row"]
        errors = []
        if row_number in seen:
            errors.append("源行重复建档")
        seen[row_number] = record["id"]
        original = expected.get(row_number)
        if not original:
            errors.append("源行不存在")
        else:
            mapping = {"product_code": "产品编码", "item_number": "货号", "specification": "规格", "unit": "单位", "scale": "规模", "name": "品名", "category_name": "类别"}
            for field, column in mapping.items():
                wanted = original[column]
                if wanted is None or (column in {"规格", "单位"} and wanted == "/"):
                    wanted = ""
                if record[field] != wanted:
                    errors.append(field)
            if trace["raw_fields"] != original:
                errors.append("原始字段不一致")
        if trace["sha256"] != source_hash or trace["sheet"] != "产品信息":
            errors.append("来源文件指纹或工作表不一致")
        if [color["value"] for color in record["colors"]] != ["无颜色"]:
            errors.append("首次导入颜色不是单独无颜色")
        if not etag:
            errors.append("缺少ETag")
        if errors:
            mismatches.append({"source_row": row_number, "fields": errors})
        digests.append(hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
    missing = sorted(set(expected) - set(seen))
    duplicate_pairs = [[36, 203], [57, 140], [94, 170], [116, 166]]
    retained = all(a in seen and b in seen and seen[a] != seen[b] for a, b in duplicate_pairs)
    return {
        "status": "PASS" if not mismatches and not missing and retained and len(seen) == len(expected) else "FAIL",
        "mode": "real-api-read-only-independent-source-comparison", "source_sha256": source_hash,
        "expected_rows": len(expected), "matched_source_rows": len(seen), "api_reads": reads,
        "missing_source_rows": missing, "mismatches": mismatches,
        "same_business_values_preserved_as_independent_records": retained,
        "records_digest": hashlib.sha256("".join(sorted(digests)).encode()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--base-url", required=True)
    arguments = parser.parse_args()
    try:
        result = verify(arguments.source, arguments.state, arguments.base_url)
    except Exception as error:
        # 保留定位堆栈，HTTP异常不会打印Cookie或响应正文。
        traceback.print_exc()
        result = {"status": "FAIL", "error_type": type(error).__name__, "message": "独立核验失败，未输出敏感响应；请检查目标、会话和源文件。"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)

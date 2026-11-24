from .errors import AiOutputInvalid


def _source_ids(result):
    found = set()
    def walk(value):
        if isinstance(value, dict):
            ids = value.get("source_ids")
            if isinstance(ids, list):
                found.update(item for item in ids if isinstance(item, str))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(result)
    return found


def validate_result(result, source):
    required = {"task", "products", "boms", "issues"}
    if (not isinstance(result, dict) or not required.issubset(result)
            or set(result) - {*required, "additional_tasks", "recognition_meta"}):
        raise AiOutputInvalid("OPENAI_OUTPUT_SCHEMA_INVALID")
    known = set(source.get("source_index", {}))
    known.update(item.get("id") for item in source.get("images", []) if isinstance(item, dict) and item.get("id"))
    unknown = _source_ids(result) - known
    if unknown:
        raise AiOutputInvalid("OPENAI_OUTPUT_SOURCE_INVALID")
    _validate_task_block(result)
    extra = result.get("additional_tasks", [])
    if not isinstance(extra, list):
        raise AiOutputInvalid("OPENAI_OUTPUT_SCHEMA_INVALID")
    seen = {"main"}
    for block in extra:
        if not isinstance(block, dict) or set(block) != {*required, "task_key"}:
            raise AiOutputInvalid("OPENAI_OUTPUT_SCHEMA_INVALID")
        key = block["task_key"]
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise AiOutputInvalid("OPENAI_OUTPUT_TASK_KEY_INVALID")
        seen.add(key)
        _validate_task_block(block)
    return result


def _validate_task_block(result):
    if (not isinstance(result["task"], dict)
            or any(not isinstance(result[key], list) for key in ("products", "boms", "issues"))
            or any(not isinstance(item, dict) for item in result["products"])):
        raise AiOutputInvalid("OPENAI_OUTPUT_SCHEMA_INVALID")
    keys = [item.get("product_key") for item in result["products"] if isinstance(item, dict)]
    if any(not isinstance(key, str) or not key.strip() for key in keys) or len(keys) != len(set(keys)):
        raise AiOutputInvalid("OPENAI_OUTPUT_PRODUCT_KEY_INVALID")
    product_keys = set(keys)
    bom_keys = set()
    for bom in result["boms"]:
        if not isinstance(bom, dict) or bom.get("product_key") not in product_keys or not isinstance(bom.get("lines"), list):
            raise AiOutputInvalid("OPENAI_OUTPUT_BOM_KEY_INVALID")
        if bom["product_key"] in bom_keys:
            raise AiOutputInvalid("OPENAI_OUTPUT_BOM_KEY_INVALID")
        bom_keys.add(bom["product_key"])
        if any(not isinstance(line, dict) for line in bom["lines"]):
            raise AiOutputInvalid("OPENAI_OUTPUT_BOM_KEY_INVALID")
        line_keys = [line.get("line_key") for line in bom["lines"]]
        if any(not isinstance(key, str) or not key.strip() for key in line_keys) or len(line_keys) != len(set(line_keys)):
            raise AiOutputInvalid("OPENAI_OUTPUT_BOM_KEY_INVALID")
        lines = {line["line_key"]: line for line in bom["lines"]}
        for line in bom["lines"]:
            parent_key = line.get("source_line_key")
            if parent_key is not None:
                parent = lines.get(parent_key) if isinstance(parent_key, str) else None
                if (parent is None or parent is line or line.get("section") != "裁剪明细"
                        or parent.get("section") not in {"面料类", "辅料类"}):
                    raise AiOutputInvalid("OPENAI_OUTPUT_BOM_KEY_INVALID")
    batches = result["task"].get("delivery_batches", [])
    if not isinstance(batches, list):
        raise AiOutputInvalid("OPENAI_OUTPUT_SCHEMA_INVALID")
    for batch in batches:
        if not isinstance(batch, dict) or batch.get("product_key") is not None and batch["product_key"] not in product_keys:
            raise AiOutputInvalid("OPENAI_OUTPUT_BATCH_KEY_INVALID")
    issue_keys = set()
    for issue in result["issues"]:
        if (not isinstance(issue, dict) or set(issue) != {"issue_key", "kind", "message", "source_ids"}
                or any(not isinstance(issue[key], str) or not issue[key].strip() for key in ("issue_key", "kind", "message"))
                or not isinstance(issue["source_ids"], list)
                or any(not isinstance(item, str) or not item for item in issue["source_ids"])
                or issue["issue_key"] in issue_keys):
            raise AiOutputInvalid("OPENAI_OUTPUT_SCHEMA_INVALID")
        issue_keys.add(issue["issue_key"])


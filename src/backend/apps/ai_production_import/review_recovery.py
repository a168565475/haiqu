"""定向修复旧识别记录：仅补恢复成功的空切数，不覆盖人工核对内容。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation


def _tasks(result):
    yield "main", result
    for task in result.get("additional_tasks", []):
        yield task["task_key"], task


def _lines(result):
    for task_key, task in _tasks(result):
        for bom in task.get("boms", []):
            for line in bom.get("lines", []):
                yield (task_key, bom["product_key"], line["line_key"]), line


def _same_number(left, right):
    if left in (None, "") or right in (None, ""):
        return False
    try:
        first, second = Decimal(str(left)), Decimal(str(right))
        return first.is_finite() and second.is_finite() and first == second
    except InvalidOperation:
        return False


def recover_empty_review_cut_counts(result, recovered, source):
    """返回修复计划；调用方负责显式授权、并发保护、审计和持久化。"""
    output, copied_source = deepcopy(result), deepcopy(source)
    candidates = dict(_lines(recovered))
    changes, restored = [], {}
    for identity, line in _lines(output):
        if line.get("section") != "管材类":
            continue
        fields = line.setdefault("erp_fields", {})
        previous = fields.get("tube_cut_piece_count")
        value = candidates.get(identity, {}).get("erp_fields", {}).get("tube_cut_piece_count", {})
        if previous is not None and (previous.get("status") != "MISSING" or previous.get("value") is not None):
            continue
        if value.get("status") != "EXTRACTED":
            continue
        fields["tube_cut_piece_count"] = deepcopy(value)
        restored[identity] = line
        changes.append({"scope": "result", "task_key": identity[0], "product_key": identity[1],
                        "line_key": identity[2], "value": value["value"], "source_ids": value["source_ids"]})

    def repair_review(review, task_key, location):
        if not isinstance(review, dict) or review.get("task_key", task_key) != task_key:
            return
        for bom in review.get("bom_plans") or []:
            for section in bom.get("sections", []):
                if section.get("title") != "管材类":
                    continue
                for line in section.get("lines", []):
                    identity = (task_key, bom.get("product_key"), line.get("ai_line_key"))
                    original = restored.get(identity)
                    current_count = line.get("tube_cut_piece_count")
                    if original is None or not (current_count is None or isinstance(current_count, str) and not current_count.strip()):
                        continue
                    # 用户改过品名、切长或原料长度时，不能继续套原来的每根切数。
                    if line.get("part_name") != original.get("part_name", {}).get("value"):
                        continue
                    fields = original["erp_fields"]
                    if not all(_same_number(line.get(key), fields.get(key, {}).get("value"))
                               for key in ("length_value", "source_raw_bar_length_m")):
                        continue
                    prior_source = line.get("ai_source", {})
                    if prior_source.get("line_key") != identity[2] or prior_source.get("part_name") != original.get("part_name"):
                        continue
                    value = fields["tube_cut_piece_count"]
                    line["tube_cut_piece_count"] = str(value["value"])
                    prior_source.setdefault("erp_fields", {})["tube_cut_piece_count"] = deepcopy(value)
                    changes.append({"scope": location, "task_key": task_key, "product_key": identity[1],
                                    "line_key": identity[2], "value": value["value"]})

    active = copied_source.get("active_task_key", "main")
    repair_review(copied_source.get("review_draft"), active, "review_draft")
    for key, state in copied_source.get("task_states", {}).items():
        repair_review(state.get("review_draft"), key, f"task_states.{key}.review_draft")
    return output, copied_source, changes

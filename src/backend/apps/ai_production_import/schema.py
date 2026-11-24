"""AI 生产导入与现行 ERP 表单对应的结构化输出契约。

模型只能提取原表证据；ERP 主档 ID 和写库动作不在本契约中。
"""

import copy

from .mapping import BATCH_FIELDS, BOM_FIELDS, BOM_SECTIONS, PRODUCT_FIELDS, TASK_FIELDS
from .recognition_rules import DEFAULT_RULES, DETAIL_KEYS


def _evidence_object(statuses, value_schema, *, require_source=False, note_rule=None):
    sources = {"type": "array", "items": {"type": "string", "pattern": ".+"}}
    if require_source:
        sources["minItems"] = 1
    note = {"type": "string"}
    if note_rule is not None:
        note["pattern"] = note_rule
    return {
        "type": "object",
        "properties": {
            "value": value_schema,
            "status": {"type": "string", "enum": statuses},
            "source_ids": sources,
            "note": note,
        },
        "required": ["value", "status", "source_ids", "note"],
        "additionalProperties": False,
    }


def _evidence_schema(value_types):
    return {"anyOf": [
        _evidence_object(["EXTRACTED"], {"type": value_types}, require_source=True),
        _evidence_object(["MISSING", "UNREADABLE"], {"type": "null"}),
        _evidence_object(["CONFLICT"], {"type": [*value_types, "null"]}),
    ]}


# 共用定义避免重复展开；OpenAI 不允许 $ref 同层带 description，字段说明放 anyOf 外层。
FIELD_SCHEMA = {"anyOf": [{"$ref": "#/$defs/evidence"}]}


def _task_field_schema(name, description):
    if name not in DEFAULT_RULES:
        return {**FIELD_SCHEMA, "description": description}
    rule, value = DEFAULT_RULES[name]
    if isinstance(value, bool):
        value_schema = {"type": "boolean", "enum": [value]}
    elif isinstance(value, int):
        value_schema = {"type": ["number", "string"], "enum": [value, str(value)]}
    else:
        value_schema = {"type": "string", "enum": [value]}
    return {
        "anyOf": [FIELD_SCHEMA, _evidence_object(
            ["DEFAULTED"], value_schema, require_source=True, note_rule=rule,
        )],
        "description": f"{description}；仅满足{rule}的已确认缺失条件才可DEFAULTED，note须注明{rule}并引用已读任务来源",
    }

DETAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "template_key": {"type": "string", "enum": list(DETAIL_KEYS)},
        "is_selected": {"anyOf": [{"$ref": "#/$defs/boolean_evidence"}], "description": "明确需要true，明确不需要false；无明确依据null，不能把非空描述当true，不允许DEFAULTED"},
        "description": {"anyOf": [{"$ref": "#/$defs/text_evidence"}], "description": "该生产明细类别的完整要求，保留适用对象、原文及来源；value只用文字或null，不允许DEFAULTED"},
    },
    "required": ["template_key", "is_selected", "description"],
    "additionalProperties": False,
}

BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "batch_key": {"type": "string", "description": "当前任务内唯一批次临时键，不是ERP ID"},
        "product_key": {"type": ["string", "null"], "description": "所属当前任务产品键；无法明确关联时null并列issue"},
        **{key: {**FIELD_SCHEMA, "description": text} for key, text in BATCH_FIELDS.items()},
    },
    "required": ["batch_key", "product_key", *BATCH_FIELDS],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {
            "type": "object",
            "properties": {
                **{name: _task_field_schema(name, description) for name, description in TASK_FIELDS.items()},
                "delivery_batches": {"type": "array", "items": BATCH_SCHEMA},
            },
            "required": [*TASK_FIELDS, "delivery_batches"],
            "additionalProperties": False,
        },
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_key": {"type": "string"},
                    **{name: {**FIELD_SCHEMA, "description": description} for name, description in PRODUCT_FIELDS.items()},
                    "details": {"type": "array", "items": DETAIL_SCHEMA, "description": "有明确要求、否定说明或待核对内容的生产明细；按模板键，不输出ERP ID"},
                },
                "required": ["product_key", *PRODUCT_FIELDS, "details"],
                "additionalProperties": False,
            },
        },
        "boms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_key": {"type": "string"},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_key": {"type": "string"},
                                "source_line_key": {"type": ["string", "null"], "description": "仅裁剪明细可填写：所用原料父行line_key须属于当前产品BOM的面料类或辅料类；其他行或无明确关联时null，关联不明并列issue"},
                                "section": {"type": "string", "enum": list(BOM_SECTIONS)},
                                "part_name": FIELD_SCHEMA,
                                "material": FIELD_SCHEMA,
                                "specification": FIELD_SCHEMA,
                                "quantity": FIELD_SCHEMA,
                                "unit": FIELD_SCHEMA,
                                "notes": FIELD_SCHEMA,
                                "raw_content": {**FIELD_SCHEMA, "description": "完整原始材料行内容，包括原数量、单位、采购/制造口径和备注"},
                                "quantity_basis": {"type": "string", "enum": ["UNIT_CONSUMPTION", "MANUFACTURING_TOTAL", "PROCUREMENT_TOTAL", "UNKNOWN"]},
                                "erp_fields": {
                                    "type": "array",
                                    "description": "只列有依据的 ERP 对应字段，字段名不能重复，不输出无关空字段",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "field": {"type": "string", "enum": list(BOM_FIELDS)},
                                            "value": FIELD_SCHEMA,
                                        },
                                        "required": ["field", "value"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["line_key", "source_line_key", "section", "part_name", "material", "specification", "quantity", "unit", "notes", "raw_content", "quantity_basis", "erp_fields"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["product_key", "lines"],
                "additionalProperties": False,
            },
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_key": {"type": "string"},
                    "kind": {"type": "string"},
                    "message": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["issue_key", "kind", "message", "source_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["task", "products", "boms", "issues"],
    "additionalProperties": False,
}

# 首任务保留原有四字段，附加任务使用同样的有限结构，不递归嵌套。
TASK_RESULT_SCHEMA = copy.deepcopy(OUTPUT_SCHEMA)
OUTPUT_SCHEMA["properties"]["additional_tasks"] = {
    "type": "array",
    "description": "同文件其他真实任务；无其他任务时空数组，不能因多颜色/批次拆单",
    "items": {
        **TASK_RESULT_SCHEMA,
        "properties": {
            "task_key": {"type": "string", "description": "唯一临时任务键，不能使用保留键main"},
            **TASK_RESULT_SCHEMA["properties"],
        },
        "required": ["task_key", *TASK_RESULT_SCHEMA["required"]],
    },
}
OUTPUT_SCHEMA["required"].append("additional_tasks")
OUTPUT_SCHEMA["$defs"] = {
    "evidence": _evidence_schema(["string", "number", "boolean"]),
    "boolean_evidence": _evidence_schema(["boolean"]),
    "text_evidence": _evidence_schema(["string"]),
}

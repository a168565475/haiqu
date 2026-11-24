import copy
import json
import unittest
from unittest.mock import patch

from apps.ai_production_import.client import SYSTEM_PROMPT, recognize
from apps.ai_production_import.errors import AiOutputInvalid, AiProviderRequestFailed
from apps.ai_production_import.mapping import normalize_cutting_max_width, normalize_erp_fields
from apps.ai_production_import.recognition_rules import RULE_VERSION, source_rule_context
from apps.ai_production_import.schema import OUTPUT_SCHEMA
from apps.ai_production_import.tests.test_client import Response, source_fixture, valid_payload
from apps.ai_production_import.tests.test_mapping import evidence, mapped_payload
from apps.ai_production_import.validation import validate_result


def missing(status="MISSING"):
    return evidence(None, status=status, sources=[])


def complete_result():
    result = mapped_payload()
    result["additional_tasks"] = []
    result["task"]["delivery_batches"] = [{
        "batch_key": "b1", "product_key": "P1", "color": evidence("黑"),
        "packaging_method": evidence("每箱2件"), "quantity": evidence(10),
        "carton_quantity": evidence(5), "delivery_date": evidence("2026-12-01"), "notes": evidence("第一批"),
    }]
    result["products"][0]["details"] = [{
        "template_key": "screen-printing", "is_selected": evidence(False),
        "description": evidence("不需要丝印"),
    }]
    return result


class RecognitionContractTests(unittest.TestCase):
    def test_a05_cutting_uses_maximum_width_and_keeps_source(self):
        for original, expected in (("111*62/58CM", "111*62CM"), ("111*62/55CM腰形", "111*62CM"),
                                   ("111*64/60CM", "111*64CM"), ("12.5 × 6/8.50 mm", "12.5*8.5MM")):
            with self.subTest(original=original):
                row = {"section": "裁剪明细", "specification": evidence(original), "erp_fields": {}}
                normalize_cutting_max_width(row)
                self.assertEqual(row["erp_fields"]["catalog_size"]["value"], expected)
                self.assertEqual(row["specification"]["value"], original)
                self.assertEqual(row["erp_fields"]["catalog_size"]["source_ids"], row["specification"]["source_ids"])
                self.assertIn("A05", row["erp_fields"]["catalog_size"]["note"])

    def test_a05_rejects_missing_units_ambiguous_sizes_and_non_cutting_rows(self):
        for original in ("63.5*18/12", "24*10/13-11*15CM", "22*16*6CM", "配22管/16孔", "0*62/58CM"):
            row = {"section": "裁剪明细", "specification": evidence(original), "erp_fields": {}}
            normalize_cutting_max_width(row)
            self.assertEqual(row["erp_fields"], {})
        for section, status in (("塑料件类", "EXTRACTED"), ("裁剪明细", "CONFLICT")):
            row = {"section": section, "specification": evidence("111*62/58CM", status=status), "erp_fields": {}}
            normalize_cutting_max_width(row)
            self.assertEqual(row["erp_fields"], {})

    def test_a05_does_not_overwrite_existing_size_or_conflict(self):
        for status in ("EXTRACTED", "CONFLICT"):
            row = {"section": "裁剪明细", "specification": evidence("111*62/58CM"),
                   "erp_fields": {"catalog_size": evidence("人工尺寸", status=status)}}
            normalize_cutting_max_width(row)
            self.assertEqual(row["erp_fields"]["catalog_size"]["value"], "人工尺寸")

    def test_a05_bad_specification_shape_does_not_raise_internal_error(self):
        for specification in (None, "111*62/58CM", [], 5):
            row = {"section": "裁剪明细", "specification": specification, "erp_fields": {}}
            normalize_cutting_max_width(row)
            self.assertEqual(row["erp_fields"], {})
            payload = mapped_payload()
            payload["boms"][0]["lines"][0].update(row)
            with self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(payload)

    def test_a05_runs_after_sparse_fields_are_normalized(self):
        payload = mapped_payload()
        row = payload["boms"][0]["lines"][0]
        row.update(section="裁剪明细", specification=evidence("111*62/58CM"), erp_fields=[])
        normalized = normalize_erp_fields(payload)
        self.assertEqual(normalized["boms"][0]["lines"][0]["erp_fields"]["catalog_size"]["value"], "111*62CM")

    def test_multitask_keeps_each_product_bom_and_batch_scope(self):
        result = complete_result()
        other = copy.deepcopy(result)
        other.pop("additional_tasks")
        other["task_key"] = "second"
        other["task"]["task_number"] = evidence("HT2")
        other["products"][0]["color"] = evidence("蓝")
        result["additional_tasks"].append(other)
        before = copy.deepcopy(result)
        normalized = normalize_erp_fields(result)
        source = {"source_index": {"s1": {}}, "images": []}
        validate_result(normalized, source)
        self.assertEqual(normalized["products"][0]["color"]["value"], before["products"][0]["color"]["value"])
        self.assertEqual(normalized["additional_tasks"][0]["products"][0]["color"]["value"], "蓝")
        self.assertEqual(result, before)

    def test_task_header_and_different_batch_dates_remain_independent(self):
        result = complete_result()
        result["task"]["delivery_date"] = evidence("2028-04-15")
        first = result["task"]["delivery_batches"][0]
        first["delivery_date"] = evidence("2028-04-15")
        second = copy.deepcopy(first)
        second.update(batch_key="b2", delivery_date={**evidence("2028-05-15"),
                       "note": "原文第二批5月15日；同任务表头2028-04-15及连续批次语境唯一确定年份。"})
        result["task"]["delivery_batches"].append(second)
        normalized = normalize_erp_fields(result)
        validate_result(normalized, {"source_index": {"s1": {}}})
        self.assertEqual(normalized["task"]["delivery_date"], result["task"]["delivery_date"])
        self.assertEqual([row["delivery_date"]["value"] for row in normalized["task"]["delivery_batches"]],
                         ["2028-04-15", "2028-05-15"])
        self.assertEqual(normalized["task"]["delivery_batches"][1]["delivery_date"]["note"], second["delivery_date"]["note"])

    def test_ambiguous_batch_year_does_not_remove_known_task_header_date(self):
        result = complete_result()
        result["task"]["delivery_date"] = evidence("2028-12-15")
        result["task"]["delivery_batches"][0]["delivery_date"] = {
            **missing(), "note": "原文1月15日，资料缺少该批次年份及可确定跨年的时间关系，待确认。"}
        normalized = normalize_erp_fields(result)
        validate_result(normalized, {"source_index": {"s1": {}}})
        self.assertEqual(normalized["task"]["delivery_date"]["value"], "2028-12-15")
        self.assertEqual(normalized["task"]["delivery_date"]["status"], "EXTRACTED")
        batch_date = normalized["task"]["delivery_batches"][0]["delivery_date"]
        self.assertIsNone(batch_date["value"])
        self.assertEqual(batch_date["status"], "MISSING")

    def test_additional_tasks_reject_reserved_duplicate_and_nested_keys(self):
        for key in ("main", "", 3):
            result = complete_result()
            other = valid_payload()
            other["task_key"] = key
            result["additional_tasks"] = [other]
            with self.subTest(key=key), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)
        result = complete_result()
        other = {"task_key": "second", **valid_payload()}
        result["additional_tasks"] = [other, copy.deepcopy(other)]
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)
        result["additional_tasks"] = [{**other, "additional_tasks": []}]
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)

    def test_detail_false_and_unknown_remain_distinct(self):
        result = complete_result()
        result["products"][0]["details"].append({
            "template_key": "packaging-instruction", "is_selected": missing("UNREADABLE"),
            "description": missing("UNREADABLE"),
        })
        details = normalize_erp_fields(result)["products"][0]["details"]
        self.assertIs(details[0]["is_selected"]["value"], False)
        self.assertEqual(details[0]["description"]["value"], "不需要丝印")
        self.assertIsNone(details[1]["is_selected"]["value"])
        self.assertEqual(details[1]["is_selected"]["status"], "UNREADABLE")

    def test_detail_rejects_unknown_template_duplicate_and_string_boolean(self):
        for mutation in ("unknown", "duplicate", "string_boolean"):
            result = complete_result()
            row = result["products"][0]["details"][0]
            if mutation == "unknown":
                row["template_key"] = "invented"
            elif mutation == "duplicate":
                result["products"][0]["details"].append(copy.deepcopy(row))
            else:
                row["is_selected"] = evidence("false")
            with self.subTest(mutation=mutation), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)

    def test_only_confirmed_default_fields_and_values_are_allowed(self):
        for key, value, rule in (("order_tolerance_percent", 0, "D16"),
                                 ("preproduction_sample_required", False, "D17"),
                                 ("is_repeat_order", False, "D18"), ("delivery_method", "SINGLE", "D23")):
            result = valid_payload()
            result["task"][key] = {**evidence(value, status="DEFAULTED"), "note": f"{rule}：已读任务区确实未填"}
            normalized = normalize_erp_fields(result)
            self.assertEqual(normalized["task"][key]["value"], value)
        for key, value, note in (("order_tolerance_percent", 5, "D16"), ("includes_tax", False, "D17"),
                                 ("is_repeat_order", False, ""), ("is_repeat_order", 0, "D18")):
            result = valid_payload()
            result["task"][key] = {**evidence(value, status="DEFAULTED"), "note": note}
            with self.subTest(key=key, value=value), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)

    def test_unreadable_and_defaults_cannot_become_fabricated_values(self):
        result = valid_payload()
        result["task"]["order_tolerance_percent"] = missing()
        self.assertIsNone(normalize_erp_fields(result)["task"]["order_tolerance_percent"]["value"])
        result["task"]["order_tolerance_percent"] = evidence(0, status="UNREADABLE")
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)
        result = complete_result()
        result["products"][0]["details"][0]["is_selected"] = {
            **evidence(False, status="DEFAULTED"), "note": "D17",
        }
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)

    def test_batch_cannot_refer_to_product_in_another_task(self):
        result = complete_result()
        result["task"]["delivery_batches"][0]["product_key"] = "P2"
        other = {"task_key": "second", **valid_payload()}
        other["products"][0]["product_key"] = "P2"
        other["boms"][0]["product_key"] = "P2"
        result["additional_tasks"] = [other]
        with self.assertRaises(AiOutputInvalid) as raised:
            validate_result(normalize_erp_fields(result), {"source_index": {"s1": {}}})
        self.assertEqual(raised.exception.code, "OPENAI_OUTPUT_BATCH_KEY_INVALID")

    def test_batch_unknown_source_and_duplicate_keys_are_rejected(self):
        result = complete_result()
        result["task"]["delivery_batches"].append(copy.deepcopy(result["task"]["delivery_batches"][0]))
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)
        result = complete_result()
        result["task"]["delivery_batches"][0]["quantity"]["source_ids"] = ["unknown"]
        with self.assertRaises(AiOutputInvalid):
            validate_result(normalize_erp_fields(result), {"source_index": {"s1": {}}})

    def test_cut_piece_uses_explicit_parent_in_its_own_bom(self):
        result = complete_result()
        raw = result["boms"][0]["lines"][0]
        raw["section"] = "辅料类"
        cut = copy.deepcopy(raw)
        cut.update(line_key="cut1", source_line_key="L1", section="裁剪明细")
        result["boms"][0]["lines"].append(cut)
        normalized = normalize_erp_fields(result)
        validate_result(normalized, {"source_index": {"s1": {}}})
        self.assertEqual(normalized["boms"][0]["lines"][1]["source_line_key"], "L1")
        for parent_key in ("unknown", "cut1"):
            result["boms"][0]["lines"][1]["source_line_key"] = parent_key
            with self.subTest(parent=parent_key), self.assertRaises(AiOutputInvalid):
                validate_result(normalize_erp_fields(result), {"source_index": {"s1": {}}})

    def test_catalog_fields_keep_distinct_values_and_reject_surface_finish(self):
        result = complete_result()
        line = result["boms"][0]["lines"][0]
        line["erp_fields"] = [
            {"field": "catalog_fabric_spec", "value": evidence("300D")},
            {"field": "catalog_finish", "value": evidence("PE")},
            {"field": "catalog_gram_weight", "value": evidence("300g/m²")},
            {"field": "catalog_tube_size", "value": evidence("开口22mm 配孔16mm")},
        ]
        fields = normalize_erp_fields(result)["boms"][0]["lines"][0]["erp_fields"]
        self.assertEqual(fields["catalog_finish"]["value"], "PE")
        self.assertEqual(fields["catalog_tube_size"]["value"], "开口22mm 配孔16mm")
        line["erp_fields"].append({"field": "surface_finish", "value": evidence("蓝白锌")})
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)

    def test_request_uses_rules_and_returns_host_provenance(self):
        payload = {"output": [{"content": [{"type": "output_text", "text": json.dumps(complete_result())}]}]}
        with patch("apps.ai_production_import.client.urllib.request.urlopen", return_value=Response(payload)) as send:
            result, _ = recognize(credentials={"api_key": "unit-test"}, controlled={"source": source_fixture()})
        body = json.loads(send.call_args.args[0].data)
        self.assertEqual(body["input"][0]["content"][0]["text"], SYSTEM_PROMPT)
        self.assertIn("A15:", SYSTEM_PROMPT)
        self.assertIn("D16:", SYSTEM_PROMPT)
        self.assertIn("任务表头明确交货日期独立填写task.delivery_date", body["input"][0]["content"][0]["text"])
        self.assertIn("T01:", body["input"][0]["content"][0]["text"])
        self.assertIn("不是新增用户业务确认", body["input"][0]["content"][0]["text"])
        self.assertIn("不使用当前年份", body["input"][0]["content"][0]["text"])
        schema_fields = body["text"]["format"]["schema"]["properties"]["task"]["properties"]
        self.assertIn("任务表头", schema_fields["delivery_date"]["description"])
        self.assertIn("省略年份仅按T01", schema_fields["delivery_batches"]["items"]["properties"]["delivery_date"]["description"])
        self.assertNotIn("D02:", SYSTEM_PROMPT)
        self.assertEqual(result["recognition_meta"]["rule_version"], RULE_VERSION)
        self.assertEqual(result["recognition_meta"]["contract_version"], 2)
        self.assertEqual(result["products"][0]["details"][0]["description"]["source_ids"], ["src_1"])

    def test_source_override_only_uses_exact_hash_and_known_rule_scope(self):
        row = {"rule_id": "A10", "source_sha256": "a" * 64, "task_number": "HT1", "instruction": "本任务棉料到厂自行裁剪"}
        self.assertEqual(source_rule_context({"source_sha256": "b" * 64}, [row]), [])
        selected = source_rule_context({"source_sha256": "a" * 64}, [row])
        self.assertEqual(selected[0]["task_number"], "HT1")
        self.assertNotIn("source_sha256", selected[0])
        with self.assertRaises(AiProviderRequestFailed):
            source_rule_context({"source_sha256": "a" * 64}, [{**row, "rule_id": "unknown"}])

    def test_structured_schema_objects_are_closed_and_all_properties_required(self):
        def inspect(schema):
            if isinstance(schema, dict):
                if schema.get("type") == "object":
                    self.assertIs(schema.get("additionalProperties"), False)
                    self.assertEqual(set(schema["properties"]), set(schema["required"]))
                for value in schema.values():
                    inspect(value)
            elif isinstance(schema, list):
                for value in schema:
                    inspect(value)
        inspect(OUTPUT_SCHEMA)
        self.assertIn("additional_tasks", OUTPUT_SCHEMA["required"])


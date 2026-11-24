import copy
import json
import unittest
from unittest.mock import patch

from apps.ai_production_import.client import SYSTEM_PROMPT, recognize
from apps.ai_production_import.errors import AiOutputInvalid
from apps.ai_production_import.mapping import BOM_FIELDS, normalize_erp_fields
from apps.ai_production_import.schema import OUTPUT_SCHEMA
from apps.ai_production_import.tests.test_client import Response, source_fixture, valid_payload


def evidence(value, status="EXTRACTED", sources=None):
    return {"value": value, "status": status, "source_ids": ["s1"] if sources is None else sources, "note": ""}


def mapped_payload():
    result = valid_payload()
    result["task"]["salesperson"] = evidence("制单人甲")
    result["products"][0]["material"] = evidence("钢材")
    result["boms"][0]["lines"] = [{
        "line_key": "L1", "section": "管材类", "part_name": evidence("型材"),
        "material": evidence("钢"), "specification": evidence("圆管 外径19mm 壁厚0.8mm 切长430mm"),
        "quantity": evidence("100"), "quantity_basis": "MANUFACTURING_TOTAL",
        "unit": evidence("支"), "notes": evidence("原制造总量100支"),
        "raw_content": evidence("型材 钢 圆管 外径19mm 壁厚0.8mm 切长430mm 制造总量100支"),
        "erp_fields": [
            {"field": "tube_shape", "value": evidence("圆管")},
            {"field": "tube_diameter", "value": evidence("19")},
            {"field": "tube_thickness", "value": evidence("0.8")},
            {"field": "length_value", "value": evidence("430")},
        ],
    }]
    return result


class ErpMappingTests(unittest.TestCase):
    def test_sparse_mapping_preserves_evidence_raw_quantity_and_source_without_mutation(self):
        original = mapped_payload()
        before = copy.deepcopy(original)
        result = normalize_erp_fields(original)
        line = result["boms"][0]["lines"][0]
        self.assertEqual(line["erp_fields"]["length_value"], evidence("430"))
        self.assertEqual(line["quantity"]["value"], "100")
        self.assertEqual(line["quantity_basis"], "MANUFACTURING_TOTAL")
        self.assertNotIn("unit_consumption", line["erp_fields"])
        self.assertNotIn("material_quantity", line)
        self.assertEqual(line["raw_content"], original["boms"][0]["lines"][0]["raw_content"])
        self.assertEqual(original, before)

    def test_all_products_and_boms_keep_their_own_keys(self):
        result = mapped_payload()
        second_product = copy.deepcopy(result["products"][0])
        second_product["product_key"] = "P2"
        result["products"].append(second_product)
        second_bom = copy.deepcopy(result["boms"][0])
        second_bom["product_key"] = "P2"
        second_bom["lines"][0]["section"] = "待确认"
        result["boms"].append(second_bom)
        normalized = normalize_erp_fields(result)
        self.assertEqual([bom["product_key"] for bom in normalized["boms"]], ["P1", "P2"])
        self.assertEqual(normalized["boms"][1]["lines"][0]["section"], "待确认")

    def test_catalog_attribute_metadata_keeps_independent_evidence_without_creating_identity(self):
        result = mapped_payload()
        line = result["boms"][0]["lines"][0]
        values = {"catalog_size": "60×40×30cm", "catalog_model": "原图号A1", "catalog_thread": "M6",
                  "catalog_width": "40mm", "catalog_thickness": "3mm"}
        line["erp_fields"] = [{"field": key, "value": evidence(value)} for key, value in values.items()]
        normalized = normalize_erp_fields(result)["boms"][0]["lines"][0]
        for key, value in values.items():
            self.assertEqual(normalized["erp_fields"][key], evidence(value))
            self.assertNotIn(key, normalized)
        self.assertNotIn("material_catalog_id", normalized)
        self.assertNotIn("material_selection", normalized)

    def test_legacy_result_remains_unchanged(self):
        original = valid_payload()
        self.assertEqual(normalize_erp_fields(original), original)

    def test_rejects_duplicate_unknown_and_master_id_fields(self):
        for invalid in ("tube_diameter", "material_quantity", "material_catalog_id", "source_raw_material_id", "fake_field"):
            with self.subTest(field=invalid):
                result = mapped_payload()
                result["boms"][0]["lines"][0]["erp_fields"].append({"field": invalid, "value": evidence("1")})
                with self.assertRaises(AiOutputInvalid):
                    normalize_erp_fields(result)

    def test_rejects_unsupported_classification_or_ambiguous_quantity_basis(self):
        for key, value in (("section", "未知辅料"), ("quantity_basis", "TOTAL"), ("quantity_basis", {}), ("erp_fields", {})):
            result = mapped_payload()
            result["boms"][0]["lines"][0][key] = value
            with self.subTest(key=key), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)

    def test_rejects_missing_source_and_invalid_or_nonfinite_field_values(self):
        for value in (evidence("19", sources=[]), evidence(None), evidence("19", status="MISSING"),
                      evidence(float("nan")), evidence({"id": "1"}), evidence("19", status={}), {"value": "19"}):
            result = mapped_payload()
            result["boms"][0]["lines"][0]["erp_fields"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)

    def test_unknown_fields_are_not_accepted_as_employee_or_product_identity(self):
        for area, name in (("task", "salesperson_id"), ("product", "product_id")):
            result = mapped_payload()
            target = result["task"] if area == "task" else result["products"][0]
            target[name] = evidence("invented-id")
            with self.subTest(area=area), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)

    def test_rejects_direct_material_identity_and_duplicate_line_keys(self):
        result = mapped_payload()
        result["boms"][0]["lines"][0]["material_catalog_id"] = "invented-id"
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)
        result = mapped_payload()
        result["boms"][0]["lines"].append(copy.deepcopy(result["boms"][0]["lines"][0]))
        with self.assertRaises(AiOutputInvalid):
            normalize_erp_fields(result)

    def test_invalid_collections_fail_as_validation_errors(self):
        for key, value in (("boms", None), ("boms", {}), ("products", [None]), ("issues", None)):
            result = mapped_payload()
            result[key] = value
            with self.subTest(key=key), self.assertRaises(AiOutputInvalid):
                normalize_erp_fields(result)

    def test_schema_contains_form_fields_and_sparse_specification_fields(self):
        schema = OUTPUT_SCHEMA["properties"]
        self.assertIn("salesperson", schema["task"]["properties"])
        self.assertIn("planned_start_date", schema["task"]["properties"])
        self.assertIn("packaging_method", schema["products"]["items"]["properties"])
        line_schema = schema["boms"]["items"]["properties"]["lines"]["items"]["properties"]
        erp_schema = line_schema["erp_fields"]
        self.assertEqual(erp_schema["type"], "array")
        self.assertEqual(set(erp_schema["items"]["properties"]["field"]["enum"]), set(BOM_FIELDS))
        self.assertNotIn("material_catalog_id", BOM_FIELDS)
        self.assertIn("待确认", line_schema["section"]["enum"])

    def test_client_restores_sources_in_new_fields_before_returning_erp_index(self):
        payload = {"output": [{"content": [{"type": "output_text", "text": json.dumps(mapped_payload())}]}]}
        with patch("apps.ai_production_import.client.urllib.request.urlopen", return_value=Response(payload)) as send:
            result, _model = recognize(credentials={"api_key": "sk-test", "model": "gpt-6.1-sol"}, controlled={"source": source_fixture()})
        mapped = result["boms"][0]["lines"][0]["erp_fields"]
        self.assertEqual(mapped["tube_diameter"]["source_ids"], ["src_1"])
        self.assertEqual(result["task"]["salesperson"]["source_ids"], ["src_1"])
        request_body = json.loads(send.call_args.args[0].data)
        self.assertEqual(request_body["input"][0]["content"][0]["text"], SYSTEM_PROMPT)
        self.assertIn("椅面/扶手/靠背是部件名", SYSTEM_PROMPT)
        self.assertIn("length_value：管材切割长度", SYSTEM_PROMPT)
        self.assertEqual([item["type"] for item in request_body["input"][1]["content"]], ["input_text"])

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from apps.ai_production_import.erp_assistant import _apply_matches, resolve_erp_matches
from apps.ai_production_import.errors import AiOutputInvalid, AiProviderRequestFailed


def evidence(value, status="EXTRACTED"):
    return {"value": value, "status": status, "source_ids": ["original-cell-id"], "note": ""}


def fixture():
    result = {"task": {"task_number": evidence("HT26142")}, "products": [{"product_key": "p1", "name": evidence("扶手椅")}],
              "boms": [{"product_key": "p1", "lines": [{
                  "line_key": "l1", "section": "管材类", "source_line_key": None, "part_name": evidence("交叉管"),
                  "material": evidence("铁"), "unit": evidence("根"), "specification": evidence("Ф16×0.5"),
                  "quantity": evidence(6), "quantity_basis": "UNIT_CONSUMPTION", "notes": evidence("人工保留"),
                  "raw_content": evidence("交叉管 铁 Φ16 壁厚0.5mm 长540mm 切11支"),
                  "erp_fields": {"length_value": evidence(540), "tube_cut_piece_count": evidence(11)},
              }]}], "issues": []}
    detail = {
        "catalog": {"id": "tube-1", "name": "交叉管", "category_key": "TUBE", "template_key": "TUBE",
                    "updated_at": "2026-11-13T00:00:00Z", "units": [], "values": []},
        "options": {"fields": [{"key": key, "kind": "text"} for key in ("material", "shape", "section_size", "thickness")],
                    "values": [
                        {"id": "material-1", "field_key": "material", "value": "铁", "parent_id": None},
                        {"id": "shape-1", "field_key": "shape", "value": "圆管", "parent_id": None},
                        {"id": "size-1", "field_key": "section_size", "value": "16", "parent_id": "shape-1"},
                        {"id": "thickness-1", "field_key": "thickness", "value": "0.5", "parent_id": None},
                    ], "units": [{"id": "unit-1", "unit_name": "根"}]},
        "required_fields": {"all": ["material", "shape", "section_size", "thickness"], "any": []},
    }
    item = {"task_key": "main", "product_key": "p1", "line_key": "l1", "status": "MATCHED", "catalog_id": "tube-1",
            "attributes": [{"key": row["field_key"], "value": row["value"]} for row in detail["options"]["values"]],
            "unit_id": "unit-1", "color_option_id": None, "completed_craft_id": None, "coating_color": None,
            "note": "材质、圆管规格及厚度与原文一致。"}
    tools = SimpleNamespace(catalog_details={"tube-1": detail}, crafts={}, audit=[])
    return result, {"matches": [item]}, tools


class AssistantMatchTests(unittest.TestCase):
    def test_catalog_metadata_does_not_authorize_unqueried_attributes(self):
        result, payload, toolbox = fixture()
        options = toolbox.catalog_details["tube-1"]["options"]
        candidates = options["values"]
        options["values"] = []
        with self.assertRaises(AiOutputInvalid) as error:
            _apply_matches(result, payload, toolbox)
        self.assertEqual(error.exception.code, "ERP_ASSISTANT_CANDIDATE_INVALID")
        options["values"] = candidates
        output = _apply_matches(result, payload, toolbox)
        self.assertEqual(output["boms"][0]["lines"][0]["erp_match"]["status"], "MATCHED")

    def test_selection_uses_current_catalog_and_preserves_original_values(self):
        result, payload, tools = fixture()
        before = copy.deepcopy(result)
        output = _apply_matches(result, payload, tools)
        line = output["boms"][0]["lines"][0]
        match = line.pop("erp_match")
        self.assertEqual(output, before)
        self.assertEqual(result, before)
        self.assertEqual(match["status"], "MATCHED")
        self.assertEqual(match["selection"]["attributes"]["section_size"], "16")
        self.assertEqual(match["selection"]["catalog_version"], "2026-11-13T00:00:00Z")
        self.assertEqual(match["unit_name"], "根")
        self.assertEqual(match["catalog"]["units"], [])

    def test_all_rows_need_one_disposition_in_their_own_task(self):
        for kind in ("missing", "duplicate", "unknown_task"):
            result, payload, tools = fixture()
            if kind == "missing":
                payload["matches"] = []
            elif kind == "duplicate":
                payload["matches"].append(copy.deepcopy(payload["matches"][0]))
            else:
                payload["matches"][0]["task_key"] = "another-task"
            with self.subTest(kind=kind), self.assertRaises(AiOutputInvalid):
                _apply_matches(result, payload, tools)

    def test_catalog_candidates_do_not_bloat_saved_line(self):
        result, payload, tools = fixture()
        catalog = tools.catalog_details["tube-1"]["catalog"]
        catalog["values"] = [{"id": str(i), "value": "目录候选内容" * 100} for i in range(1000)]
        catalog["base_warehouse_id"] = "warehouse-not-needed"
        catalog["units"] = [{"id": "allowed-1", "scope": "BASE", "unit_id": "unit-1", "unit_name": "根"},
                            {"id": "allowed-2", "scope": "SPRAY", "unit_id": "unit-1", "unit_name": "根"}]
        selected = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]["catalog"]
        self.assertEqual(selected["values"], [])
        self.assertEqual(len(selected["units"]), 1)
        self.assertLess(len(json.dumps(selected)), 1000)
        self.assertNotIn("base_warehouse_id", selected)
        self.assertEqual(len(catalog["values"]), 1000)

    def test_unqueried_catalog_and_unknown_or_duplicate_attributes_rejected(self):
        for kind in ("catalog", "value", "key", "duplicate", "unit", "shape_parent"):
            result, payload, tools = fixture()
            item = payload["matches"][0]
            if kind == "catalog": item["catalog_id"] = "not-queried"
            elif kind == "value": item["attributes"][0]["value"] = "invented"
            elif kind == "key": item["attributes"][0]["key"] = "secret"
            elif kind == "duplicate": item["attributes"].append(copy.deepcopy(item["attributes"][0]))
            elif kind == "unit": item["unit_id"] = "unknown-unit"
            else: tools.catalog_details["tube-1"]["options"]["values"][2]["parent_id"] = "other-shape"
            with self.subTest(kind=kind), self.assertRaises(AiOutputInvalid) as error:
                _apply_matches(result, payload, tools)
            self.assertEqual(error.exception.code, "ERP_ASSISTANT_CANDIDATE_INVALID")

    def test_missing_required_attribute_stays_partial_without_fabricating_it(self):
        result, payload, tools = fixture()
        payload["matches"][0]["attributes"].pop()
        line = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]
        self.assertEqual(line["erp_match"]["status"], "PARTIAL")
        self.assertIsNone(line["erp_match"]["selection"])
        self.assertIn("thickness", line["erp_match"]["note"])
        self.assertEqual(line["specification"]["value"], "Ф16×0.5")

    def test_same_name_in_another_category_does_not_move_material(self):
        result, payload, tools = fixture()
        tools.catalog_details["tube-1"]["catalog"]["category_key"] = "PLASTIC"
        match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
        self.assertEqual(match["status"], "CONFLICT")
        self.assertEqual(match["section"], "管材类")
        self.assertIsNone(match["selection"])

    def test_ordinary_materials_follow_verified_catalog_section(self):
        for original_section, name, unit in (("塑料件类", "袋口珠", "个"), ("面料类", "网布", "米")):
            result, payload, tools = fixture()
            line = result["boms"][0]["lines"][0]
            line.update(section=original_section, part_name=evidence(name), unit=evidence(unit))
            detail = tools.catalog_details["tube-1"]
            detail["catalog"].update(name=name, category_key="AUXILIARY", template_key="OTHER")
            detail["options"]["units"][0]["unit_name"] = unit
            with self.subTest(name=name):
                mapped = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]
                self.assertEqual(mapped["erp_match"]["status"], "MATCHED")
                self.assertEqual(mapped["erp_match"]["section"], "辅料类")
                self.assertIsNotNone(mapped["erp_match"]["selection"])
                self.assertEqual(mapped["section"], original_section)

    def test_cutting_section_cannot_be_reclassified_as_ordinary_material(self):
        result, payload, tools = fixture()
        result["boms"][0]["lines"][0]["section"] = "裁剪明细"
        tools.catalog_details["tube-1"]["catalog"].update(category_key="AUXILIARY", template_key="OTHER")
        match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
        self.assertEqual(match["status"], "CONFLICT")
        self.assertEqual(match["section"], "裁剪明细")
        self.assertIsNone(match["selection"])

    def test_reference_is_not_a_way_to_drop_unmatched_real_material(self):
        for kind in ("ordinary", "summary", "parent"):
            result, payload, tools = fixture()
            line = result["boms"][0]["lines"][0]
            item = payload["matches"][0]
            item.update(status="REFERENCE", catalog_id=None, attributes=[], unit_id=None)
            if kind != "ordinary":
                line.update(section="待确认", part_name=evidence("总共：面料汇总"))
            if kind == "parent":
                child = copy.deepcopy(line)
                child.update(line_key="l2", source_line_key="l1", section="裁剪明细", part_name=evidence("椅面"))
                result["boms"][0]["lines"].append(child)
                extra = copy.deepcopy(item)
                extra.update(line_key="l2", status="NOT_FOUND")
                payload["matches"].append(extra)
            match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
            with self.subTest(kind=kind):
                self.assertEqual(match["status"], "REFERENCE" if kind == "summary" else "CONFLICT")

    def test_source_conflict_remains_unresolved(self):
        for field in ("part_name", "material", "specification", "unit"):
            result, payload, tools = fixture()
            result["boms"][0]["lines"][0][field] = evidence(None, "CONFLICT")
            match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
            with self.subTest(field=field):
                self.assertEqual(match["status"], "CONFLICT")
                self.assertIsNone(match["selection"])

    def test_identity_field_conflicts_cannot_be_resolved_by_catalog_choice(self):
        for field in ("catalog_size", "tube_thickness", "raw_material", "fabric_color_code"):
            result, payload, tools = fixture()
            result["boms"][0]["lines"][0]["erp_fields"][field] = evidence(None, "CONFLICT")
            match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
            with self.subTest(field=field):
                self.assertEqual(match["status"], "CONFLICT")
                self.assertIsNone(match["selection"])

    def test_manufacturing_quantity_conflict_does_not_change_material_identity(self):
        result, payload, tools = fixture()
        result["boms"][0]["lines"][0]["erp_fields"]["unit_consumption"] = evidence(None, "CONFLICT")
        line = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]
        self.assertEqual(line["erp_match"]["status"], "MATCHED")
        self.assertEqual(line["erp_fields"]["unit_consumption"]["status"], "CONFLICT")

    def test_quality_and_delivery_conflicts_preserve_valid_material_selection(self):
        result, payload, tools = fixture()
        line = result["boms"][0]["lines"][0]
        line["notes"] = evidence("盐雾12/24小时待确认", "CONFLICT")
        line["erp_fields"]["quality_requirements"] = evidence("盐雾12/24小时", "CONFLICT")
        result["task"]["delivery_date"] = evidence(None, "CONFLICT")
        result["issues"] = [{"message": "盐雾要求及交期待核对"}]
        output = _apply_matches(result, payload, tools)
        mapped = output["boms"][0]["lines"][0]
        self.assertEqual(mapped["erp_match"]["status"], "MATCHED")
        self.assertEqual(mapped["notes"], line["notes"])
        self.assertEqual(mapped["erp_fields"]["quality_requirements"], line["erp_fields"]["quality_requirements"])
        self.assertEqual(output["task"], result["task"])
        self.assertEqual(output["issues"], result["issues"])

    def test_coating_color_uses_queried_spray_value_and_preserves_complete_source(self):
        for category, section, source_key in (("TUBE", "管材类", "tube_coating_color"),
                                             ("HARDWARE", "五金件", "powder_coating_color")):
            result, payload, tools = fixture()
            line = result["boms"][0]["lines"][0]
            line["section"] = section
            line["erp_fields"][source_key] = evidence("黑色亮光喷塑")
            detail = tools.catalog_details["tube-1"]
            detail["catalog"].update(category_key=category, spray_enabled=True)
            detail["spray_options"] = {"values": [{"field_key": "color", "value": "黑色"}]}
            payload["matches"][0]["coating_color"] = "黑色"
            with self.subTest(category=category):
                mapped = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]
                self.assertEqual(mapped["erp_match"]["status"], "MATCHED")
                expected = {"powder_coating_color": "黑色"}
                if category == "TUBE": expected["tube_coating_color"] = "黑色"
                self.assertEqual(mapped["erp_match"]["field_updates"], expected)
                self.assertEqual(mapped["erp_fields"][source_key]["value"], "黑色亮光喷塑")
                self.assertNotIn("coating_color", mapped["erp_match"]["selection"]["attributes"])

    def test_missing_or_unverified_spray_color_cannot_be_matched(self):
        for kind in ("missing", "base_only", "wrong_spray_value", "disabled", "source_conflict"):
            result, payload, tools = fixture()
            line = result["boms"][0]["lines"][0]
            line["erp_fields"]["tube_coating_color"] = evidence("黑色亮光喷塑", "CONFLICT" if kind == "source_conflict" else "EXTRACTED")
            detail = tools.catalog_details["tube-1"]
            detail["catalog"]["spray_enabled"] = kind != "disabled"
            detail["options"]["values"].append({"id": "base-black", "field_key": "color", "value": "黑色"})
            detail["spray_options"] = {"values": [{"field_key": "color", "value": "白色" if kind == "wrong_spray_value" else "黑色"}]}
            if kind == "base_only": detail["spray_options"]["values"] = []
            payload["matches"][0]["coating_color"] = None if kind == "missing" else "黑色"
            with self.subTest(kind=kind):
                match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
                self.assertEqual(match["status"], "PARTIAL")
                self.assertIsNone(match["selection"])
                self.assertEqual(match["field_updates"], {})

    def test_coating_color_cannot_be_invented_without_source_requirement(self):
        result, payload, tools = fixture()
        detail = tools.catalog_details["tube-1"]
        detail["catalog"]["spray_enabled"] = True
        detail["spray_options"] = {"values": [{"field_key": "color", "value": "黑色"}]}
        payload["matches"][0]["coating_color"] = "黑色"
        with self.assertRaises(AiOutputInvalid) as error:
            _apply_matches(result, payload, tools)
        self.assertEqual(error.exception.code, "ERP_ASSISTANT_CANDIDATE_INVALID")

    def test_material_matching_does_not_change_quantity_unit_basis(self):
        for source_unit, target_unit, status in (("米", "个", "CONFLICT"), ("米", "m", "MATCHED"),
                                                 ("PCS", "个", "MATCHED"), ("千克", "g", "CONFLICT"),
                                                 ("公斤", "kg", "MATCHED"), ("", "米", "PARTIAL")):
            result, payload, tools = fixture()
            line = result["boms"][0]["lines"][0]
            line.update(section="五金件", unit=evidence(source_unit), quantity=evidence("0.71"))
            detail = tools.catalog_details["tube-1"]
            detail["catalog"].update(category_key="HARDWARE", template_key="HARDWARE")
            detail["options"]["units"][0]["unit_name"] = target_unit
            mapped = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]
            with self.subTest(source=source_unit, target=target_unit):
                self.assertEqual(mapped["erp_match"]["status"], status)
                self.assertEqual(mapped["quantity"]["value"], "0.71")
                self.assertEqual(mapped["unit"]["value"], source_unit)
                if status != "MATCHED": self.assertIsNone(mapped["erp_match"]["selection"])

    def test_cut_piece_requires_queried_cutting_craft_and_source(self):
        for kind in ("valid", "max_width", "no_craft", "no_source", "wrong_craft", "source_unmatched", "source_wrong_unit", "source_cotton"):
            result, payload, tools = fixture()
            line, item = result["boms"][0]["lines"][0], payload["matches"][0]
            line.update(section="裁剪明细", source_line_key="fabric-source")
            detail = tools.catalog_details["tube-1"]
            detail["catalog"].update(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")
            item["completed_craft_id"] = "craft-1"
            tools.crafts["craft-1"] = {"id": "craft-1", "craft_type": "INTERNAL", "code": "CUTTING"}
            source = copy.deepcopy(line)
            source.update(line_key="fabric-source", section="面料类", source_line_key=None, unit=evidence("米"))
            result["boms"][0]["lines"].append(source)
            source_match = copy.deepcopy(item)
            source_match.update(line_key="fabric-source", catalog_id="fabric-1", completed_craft_id=None,
                                attributes=[{"key": "width", "value": "1.5m"}])
            payload["matches"].append(source_match)
            tools.catalog_details["fabric-1"] = {
                "catalog": {"id": "fabric-1", "name": "面料", "category_key": "FABRIC", "template_key": "FABRIC", "updated_at": "v1"},
                "options": {"fields": [{"key": "width", "kind": "text"}],
                            "values": [{"id": "width-1", "field_key": "width", "value": "1.5m"}],
                            "units": [{"id": "unit-1", "unit_name": "米"}]},
                "required_fields": {"all": [], "any": ["width"]},
            }
            if kind == "no_craft": item["completed_craft_id"] = None
            if kind == "no_source": line["source_line_key"] = None
            if kind == "wrong_craft": tools.crafts["craft-1"]["code"] = "SEWING"
            if kind == "source_unmatched": source_match["status"] = "PARTIAL"
            if kind == "source_wrong_unit": tools.catalog_details["fabric-1"]["options"]["units"][0]["unit_name"] = "个"
            if kind == "source_cotton":
                source["section"] = "辅料类"
                tools.catalog_details["fabric-1"]["catalog"].update(category_key="AUXILIARY", template_key="COTTON")
            if kind == "max_width":
                line.update(specification=evidence("96×49/45.5 cm"), unit=evidence("个"))
                line["erp_fields"]["catalog_size"] = evidence("96×49 cm")
                detail["options"] = {"fields": [{"key": "size", "kind": "text"}],
                                     "values": [{"id": "cut-size", "field_key": "size", "value": "96×49 cm"}],
                                     "units": [{"id": "unit-1", "unit_name": "个"}]}
                detail["required_fields"] = {"all": ["size"], "any": []}
                item["attributes"] = [{"key": "size", "value": "96×49 cm"}]
            with self.subTest(kind=kind):
                if kind == "wrong_craft":
                    with self.assertRaises(AiOutputInvalid): _apply_matches(result, payload, tools)
                    continue
                match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
                self.assertEqual(match["status"], "MATCHED" if kind in {"valid", "max_width"} else "PARTIAL")
                if kind in {"valid", "max_width"}:
                    self.assertEqual(match["selection"]["processing_state"], "PROCESSED")
                    self.assertEqual(match["selection"]["semi_kind"], "CUTTING")

    def test_fabric_color_needs_exact_queried_identity(self):
        for color_id in (None, "a", "local", "other"):
            result, payload, tools = fixture()
            line, item = result["boms"][0]["lines"][0], payload["matches"][0]
            line["section"] = "面料类"
            detail = tools.catalog_details["tube-1"]
            detail["catalog"].update(category_key="FABRIC", template_key="FABRIC")
            detail["options"]["fields"] = [{"key": "color", "kind": "text"}]
            detail["options"]["values"] = [
                {"id": "a", "field_key": "color", "value": "黑色", "product_color_id": "color-a", "color_card": "卡A", "color_name": "黑色"},
                {"id": "local", "field_key": "color", "value": "黑色", "product_color_id": None, "color_card": "卡B", "color_name": "黑色"},
            ]
            detail["options"]["units"][0]["unit_name"] = "米"
            detail["required_fields"] = {"all": ["color"], "any": []}
            item.update(attributes=[{"key": "color", "value": "黑色"}], color_option_id=color_id)
            with self.subTest(color_id=color_id):
                if color_id == "other":
                    with self.assertRaises(AiOutputInvalid): _apply_matches(result, payload, tools)
                    continue
                match = _apply_matches(result, payload, tools)["boms"][0]["lines"][0]["erp_match"]
                self.assertEqual(match["status"], "PARTIAL" if color_id is None else "MATCHED")
                if color_id:
                    self.assertEqual(match["selection"]["color_card"], "卡A" if color_id == "a" else "卡B")
                    self.assertEqual(match["selection"]["product_color_id"], "color-a" if color_id == "a" else None)


def response(payload=None, output=None):
    return {"status": "completed", "output": output if output is not None else [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}]}


class AssistantLoopTests(unittest.TestCase):
    def _source(self):
        return {"original_name": "task.xlsx", "source_index": {}, "sheets": [], "previous_recognition": {"do_not_send": True}}

    def test_material_reasoning_uses_its_own_setting_across_tool_rounds(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "query"}]
        toolbox.execute = lambda name, args: {"found": True}
        call = {"type": "function_call", "name": "query", "call_id": "call-1", "arguments": "{}"}
        for model, selected, expected in (
            ("gpt-6-astra", None, "medium"),
            ("gpt-6-astra", "auto", "medium"),
            ("gpt-6-astra", "xhigh", "xhigh"),
            ("custom-model", "low", "low"),
            ("custom-model", "auto", None),
        ):
            credentials = {"model": model, "base_url": "https://example.test/v1", "document_reasoning_effort": "high"}
            if selected is not None:
                credentials["material_reasoning_effort"] = selected
            with self.subTest(model=model, selected=selected), \
                 patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
                 patch('apps.ai_production_import.erp_assistant.request_response',
                       side_effect=[response(output=[call]), response(payload)]) as transport:
                resolve_erp_matches(result=result, source=self._source(), credentials=credentials, request=object())
                self.assertEqual(transport.call_count, 2)
                for request in transport.call_args_list:
                    self.assertEqual(request.args[1].get("reasoning"), {"effort": expected} if expected else None)

    def test_tools_round_trip_retains_reasoning_and_original_result_without_source_hashes(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda name, args: {"catalog": "tube-1"}
        seen = []
        first_output = [{"type": "reasoning", "id": "reasoning-1", "summary": []},
                        {"type": "function_call", "name": "get_erp_materials", "call_id": "call-1", "arguments": '{"catalog_ids":["tube-1"]}'}]
        def transport(credentials, body, *, deadline):
            seen.append(copy.deepcopy(body))
            return response(output=first_output) if len(seen) == 1 else response(payload)
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=transport):
            output = resolve_erp_matches(result=result, source=self._source(), credentials={"api_key": "not-output", "model": "gpt-6-astra"}, request=object())
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["rounds"], 2)
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["tool_call_count"], 1)
        self.assertEqual([item for item in seen[1]["input"] if item.get("type") in {"reasoning", "function_call"}], first_output)
        self.assertEqual(next(item for item in seen[1]["input"] if item.get("type") == "function_call_output")["call_id"], "call-1")
        serialized = json.dumps(seen)
        self.assertNotIn("original-cell-id", serialized)
        self.assertNotIn("do_not_send", serialized)
        self.assertNotIn("not-output", serialized)
        self.assertNotIn("erp_match", result["boms"][0]["lines"][0])

    def test_parallel_function_calls_are_all_returned(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "query"}]
        executed, inputs = [], []
        toolbox.execute = lambda name, args: executed.append(args) or {"found": True}
        calls = [{"type": "function_call", "name": "query", "call_id": f"call-{i}", "arguments": json.dumps({"n": i})} for i in range(3)]
        def transport(credentials, body, *, deadline):
            inputs.append(copy.deepcopy(body["input"]))
            return response(output=calls) if len(inputs) == 1 else response(payload)
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=transport):
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(executed, [{"n": 0}, {"n": 1}, {"n": 2}])
        self.assertEqual(len([row for row in inputs[1] if row.get("type") == "function_call_output"]), 3)

    def test_unknown_tool_or_invalid_arguments_never_execute(self):
        for name, arguments in (("write_sql", "{}"), ("query", "not-json"), ("query", "[]")):
            result, _, toolbox = fixture()
            toolbox.definitions = [{"type": "function", "name": "query"}]
            toolbox.execute = lambda *args: self.fail("不得执行无效调用")
            call = {"type": "function_call", "name": name, "arguments": arguments, "call_id": "call-1"}
            with self.subTest(name=name, arguments=arguments), \
                 patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
                 patch('apps.ai_production_import.erp_assistant.request_response', return_value=response(output=[call])), \
                 self.assertRaises(AiOutputInvalid):
                resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())

    def test_round_limit_without_final_result_fails_explicitly(self):
        result, _, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "query"}]
        toolbox.execute = lambda *args: {}
        calls = [{"type": "function_call", "name": "query", "arguments": "{}", "call_id": "call-1"}]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', return_value=response(output=calls)), \
             patch('apps.ai_production_import.erp_assistant.MAX_ROUNDS', 1), \
             self.assertRaises(AiProviderRequestFailed) as error:
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(error.exception.code, "ERP_ASSISTANT_LOOKUP_LIMIT")

    def test_image_data_in_prior_model_text_is_not_sent(self):
        result, payload, toolbox = fixture()
        result["boms"][0]["lines"][0]["raw_content"] = evidence("data:image/png;base64,private-image")
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "call_id": "query-1", "arguments": "{}"}
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), response(payload)]) as transport:
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        sent = json.dumps(transport.call_args.args[1])
        self.assertNotIn("private-image", sent)

    def test_final_result_requires_actual_erp_query(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = []
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', return_value=response(payload)), \
             self.assertRaises(AiOutputInvalid) as error:
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(error.exception.path, "tools")

    def test_not_found_requires_successful_material_search(self):
        for tool, tool_result, allowed in (("get_production_crafts", {"crafts": []}, False),
                                          ("search_erp_materials", {"error": "FORBIDDEN"}, False),
                                          ("search_erp_materials", {"results": []}, True)):
            result, payload, toolbox = fixture()
            payload["matches"][0].update(status="NOT_FOUND", catalog_id=None, attributes=[], unit_id=None)
            toolbox.definitions = [{"type": "function", "name": tool}]
            toolbox.execute = lambda *args: tool_result
            call = {"type": "function_call", "name": tool, "arguments": "{}", "call_id": "query-1"}
            with self.subTest(tool=tool, allowed=allowed), \
                 patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
                 patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), response(payload), response(payload)]):
                if allowed:
                    output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
                    self.assertEqual(output["boms"][0]["lines"][0]["erp_match"]["status"], "NOT_FOUND")
                else:
                    with self.assertRaises(AiOutputInvalid):
                        resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())

    def test_invalid_final_candidate_gets_one_correction_with_line_path_and_same_deadline(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "query-1"}
        incorrect = copy.deepcopy(payload)
        incorrect["matches"][0]["catalog_id"] = "unqueried-id"
        replies = [response(output=[call]), response(incorrect), response(payload)]
        requests = []
        def transport(credentials, body, *, deadline):
            requests.append({"body": copy.deepcopy(body), "deadline": deadline})
            return replies[len(requests) - 1]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=transport), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 103, 104, 105]):
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([row["deadline"] for row in requests], [550, 550, 700])
        feedback = next(item["content"][0]["text"] for item in requests[2]["body"]["input"]
                        if item.get("role") == "user" and "校验数据" in item["content"][0]["text"])
        self.assertIn("matches[main/p1/l1]", feedback)
        self.assertIn("ERP_ASSISTANT_CANDIDATE_INVALID", feedback)
        self.assertIn(replies[1]["output"][0], requests[2]["body"]["input"])
        self.assertEqual(output["boms"][0]["lines"][0]["erp_match"]["status"], "MATCHED")
        self.assertEqual(len(output["recognition_meta"]["erp_assistant"]["validation_repairs"]), 1)

    def test_repeated_invalid_final_output_stops_after_one_correction(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "query-1"}
        payload["matches"] = []
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), response(payload), response(payload)]) as transport, \
             self.assertRaises(AiOutputInvalid) as error:
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(error.exception.code, "ERP_ASSISTANT_INCOMPLETE")
        self.assertEqual(transport.call_count, 3)

    def test_zero_query_result_can_query_after_single_feedback(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "query-1"}
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(payload), response(output=[call]), response(payload)]):
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["tool_call_count"], 1)
        self.assertEqual(len(output["recognition_meta"]["erp_assistant"]["validation_repairs"]), 1)

    def test_no_correction_when_round_or_time_budget_exhausted(self):
        for limit, times, expected in ((2, [100, 101, 102, 103], "ERP_ASSISTANT_INCOMPLETE"),
                                       (8, [100, 101, 102, 103, 701], "OPENAI_TIMEOUT")):
            result, payload, toolbox = fixture()
            toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
            toolbox.execute = lambda *args: {"found": True}
            call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "query-1"}
            payload["matches"] = []
            with self.subTest(limit=limit), patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
                 patch('apps.ai_production_import.erp_assistant.MAX_ROUNDS', limit), \
                 patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=times), \
                 patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), response(payload)]) as transport, \
                 self.assertRaises((AiOutputInvalid, AiProviderRequestFailed)) as error:
                resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
            self.assertEqual(error.exception.code, expected)
            self.assertEqual(transport.call_count, 2)

    def test_query_round_budget_reserves_final_output_and_one_correction(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        calls = [{"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": f"call-{i}"} for i in range(2)]
        replies = [response(output=[calls[0]]), response(output=[calls[1]]), response({"matches": []}), response(payload)]
        seen = []
        def transport(credentials, body, *, deadline):
            seen.append(copy.deepcopy(body))
            return replies[len(seen) - 1]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.MAX_QUERY_ROUNDS', 2), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=transport):
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([body["tool_choice"] for body in seen], ["auto", "auto", "none", "none"])
        self.assertIn("查询阶段已结束", seen[2]["input"][-1]["content"][0]["text"])
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["query_rounds"], 2)
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["final_rounds"], 2)
        self.assertEqual(output["boms"][0]["lines"][0]["erp_match"]["status"], "MATCHED")

    def test_tool_call_cap_returns_budget_error_then_finishes_existing_work(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        executed = []
        toolbox.execute = lambda name, args: executed.append(name) or {"found": True}
        calls = [{"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": f"call-{i}"} for i in range(61)]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=calls), response(payload)]) as transport:
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(len(executed), 60)
        last = transport.call_args.args[1]
        self.assertEqual(last["tool_choice"], "none")
        tool_outputs = [item for item in last["input"] if item.get("type") == "function_call_output"]
        self.assertEqual(len(tool_outputs), 61)
        self.assertEqual(json.loads(tool_outputs[-1]["output"])["error"], "LOOKUP_BUDGET_EXHAUSTED")
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["budget_skipped_tool_calls"], 1)

    def test_query_timeout_uses_reserved_time_for_final_output_without_extending_total(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 103, 550, 551]), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), AiProviderRequestFailed("OPENAI_TIMEOUT"), response(payload)]) as transport:
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([call.kwargs["deadline"] for call in transport.call_args_list], [550, 550, 700])
        self.assertEqual(transport.call_args.args[1]["tool_choice"], "none")
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["tool_call_count"], 1)

    def test_time_reserve_closes_queries_before_round_limit(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 560]), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), response(payload)]) as transport:
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([call.args[1]["tool_choice"] for call in transport.call_args_list], ["auto", "none"])
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["query_rounds"], 1)

    def test_network_retry_keeps_same_round_history_and_deadline(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        executed, seen = [], []
        toolbox.execute = lambda name, args: executed.append(name) or {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        def transport(credentials, body, *, deadline):
            seen.append({"body": copy.deepcopy(body), "deadline": deadline})
            if len(seen) == 2:
                raise AiProviderRequestFailed("OPENAI_NETWORK_ERROR")
            return response(output=[call]) if len(seen) == 1 else response(payload)
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 103, 104]), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=transport):
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(seen[1], seen[2])
        self.assertEqual([request["deadline"] for request in seen], [550, 550, 550])
        self.assertEqual(executed, ["get_erp_materials"])
        self.assertEqual(sum(item.get("type") == "function_call_output" for item in seen[2]["body"]["input"]), 1)
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["network_retries"], 1)
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["rounds"], 2)

    def test_network_retry_limit_applies_across_all_rounds(self):
        result, _, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        replies = [AiProviderRequestFailed("OPENAI_NETWORK_ERROR"), response(output=[call]),
                   AiProviderRequestFailed("OPENAI_NETWORK_ERROR")]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=replies) as transport, \
             self.assertRaises(AiProviderRequestFailed) as error:
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(error.exception.code, "OPENAI_NETWORK_ERROR")
        self.assertEqual(transport.call_count, 3)

    def test_final_output_network_retry_keeps_total_deadline_and_final_round(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        replies = [response(output=[call]), AiProviderRequestFailed("OPENAI_NETWORK_ERROR"), response(payload)]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 560, 561]), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=replies) as transport:
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([call.kwargs["deadline"] for call in transport.call_args_list], [550, 700, 700])
        self.assertEqual([call.args[1]["tool_choice"] for call in transport.call_args_list], ["auto", "none", "none"])
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["final_rounds"], 1)
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["network_retries"], 1)

    def test_network_retry_does_not_retry_auth_quota_or_structure_errors(self):
        failures = [AiProviderRequestFailed("OPENAI_AUTH_FAILED"), AiProviderRequestFailed("OPENAI_RATE_LIMITED"),
                    AiProviderRequestFailed("OPENAI_BAD_REQUEST"), AiOutputInvalid("OPENAI_RESPONSE_JSON_INVALID")]
        for failure in failures:
            result, _, toolbox = fixture()
            toolbox.definitions = []
            with self.subTest(code=failure.code), patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
                 patch('apps.ai_production_import.erp_assistant.request_response', side_effect=failure) as transport, \
                 self.assertRaises(type(failure)) as error:
                resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
            self.assertEqual(error.exception.code, failure.code)
            self.assertEqual(transport.call_count, 1)

    def test_network_error_at_query_deadline_closes_tools_instead_of_retrying_query(self):
        result, payload, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        replies = [response(output=[call]), AiProviderRequestFailed("OPENAI_NETWORK_ERROR"), response(payload)]
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 103, 550, 551, 552]), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=replies) as transport:
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([call.kwargs["deadline"] for call in transport.call_args_list], [550, 550, 700])
        self.assertEqual(transport.call_args.args[1]["tool_choice"], "none")
        self.assertEqual(output["recognition_meta"]["erp_assistant"]["network_retries"], 0)

    def test_network_error_after_total_deadline_stops_without_retry(self):
        result, _, toolbox = fixture()
        toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
        toolbox.execute = lambda *args: {"found": True}
        call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.time.monotonic', side_effect=[100, 101, 102, 560, 700]), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), AiProviderRequestFailed("OPENAI_NETWORK_ERROR")]) as transport, \
             self.assertRaises(AiProviderRequestFailed) as error:
            resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual(error.exception.code, "OPENAI_TIMEOUT")
        self.assertEqual(transport.call_count, 2)

    def test_selective_attribute_lookup_reuses_queried_candidates_for_repeated_rows(self):
        result, payload, toolbox = fixture()
        options = toolbox.catalog_details["tube-1"]["options"]
        candidates, executed, requests = options["values"], [], []
        options["values"] = []
        for index in range(2, 4):
            line, item = copy.deepcopy(result["boms"][0]["lines"][0]), copy.deepcopy(payload["matches"][0])
            line["line_key"] = item["line_key"] = f"l{index}"
            result["boms"][0]["lines"].append(line)
            payload["matches"].append(item)
        reference = "TUBE/TUBE/BASE"
        queries = [{"options_ref": reference, "field_key": row["field_key"], "query": row["value"]} for row in candidates]
        toolbox.definitions = [{"type": "function", "name": name} for name in ("get_erp_materials", "search_erp_attributes")]
        def execute(name, args):
            executed.append((name, copy.deepcopy(args)))
            if name == "get_erp_materials":
                return {"materials": [{"catalog": {"id": "tube-1"}, "options_ref": reference}],
                        "templates": [{"options_ref": reference, "options": copy.deepcopy(options)}]}
            options["values"] = candidates
            return {"results": [{**query, "values": [row], "has_more": False} for query, row in zip(queries, candidates)]}
        toolbox.execute = execute
        calls = [{"type": "function_call", "name": "get_erp_materials", "arguments": '{"catalog_ids":["tube-1"]}', "call_id": "catalog-1"},
                 {"type": "function_call", "name": "search_erp_attributes", "arguments": json.dumps({"queries": queries}), "call_id": "attributes-1"}]
        def transport(credentials, body, *, deadline):
            requests.append(copy.deepcopy(body))
            return response(output=[calls[len(requests) - 1]]) if len(requests) <= 2 else response(payload)
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=transport):
            output = resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
        self.assertEqual([name for name, _ in executed], ["get_erp_materials", "search_erp_attributes"])
        self.assertEqual(executed[1][1], {"queries": queries})
        metadata = json.loads(next(item["output"] for item in requests[1]["input"] if item.get("type") == "function_call_output"))
        self.assertEqual(metadata["templates"][0]["options"]["values"], [])
        self.assertEqual([line["erp_match"]["status"] for line in output["boms"][0]["lines"]], ["MATCHED"] * 3)

    def test_diagnostics_record_metrics_without_business_text_or_secrets(self):
        result, payload, toolbox = fixture()
        result["boms"][0]["lines"][0]["notes"] = evidence("business-text-sentinel")
        toolbox.definitions = [{"type": "function", "name": "search_erp_materials"}]
        tool_result = {"results": [{"description": "tool-business-sentinel"}]}
        toolbox.execute = lambda *args: tool_result
        call = {"type": "function_call", "name": "search_erp_materials", "arguments": '{"queries":[{"query":"query-secret-sentinel"}]}', "call_id": "call-1"}
        final = response(payload)
        final["usage"] = {"input_tokens": 321, "output_tokens": 37, "input_tokens_details": "ignored-usage-sentinel"}
        with patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
             patch('apps.ai_production_import.erp_assistant.MAX_QUERY_ROUNDS', 1), \
             patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), final]), \
             self.assertLogs('apps.ai_production_import.erp_assistant', level='INFO') as captured:
            resolve_erp_matches(result=result, source=self._source(), credentials={"api_key": "key-secret-sentinel", "base_url": "header-secret-sentinel"}, request=object())
        logs = "\n".join(captured.output)
        for marker in ("business-text-sentinel", "tool-business-sentinel", "query-secret-sentinel", "ignored-usage-sentinel",
                       "key-secret-sentinel", "header-secret-sentinel", "Authorization"):
            self.assertNotIn(marker, logs)
        for marker in ("phase=query round=1", "phase=final round=2", "request_bytes=", "elapsed_ms=",
                       "input_tokens=321 output_tokens=37", "name=search_erp_materials query_count=1", "output_bytes="):
            self.assertIn(marker, logs)

    def test_failure_diagnostics_keep_round_and_call_count_and_reraise(self):
        failures = [AiProviderRequestFailed("OPENAI_AUTH_FAILED"), ValueError("internal-business-sentinel")]
        for failure in failures:
            result, _, toolbox = fixture()
            toolbox.definitions = [{"type": "function", "name": "get_erp_materials"}]
            toolbox.execute = lambda *args: {"found": True}
            call = {"type": "function_call", "name": "get_erp_materials", "arguments": "{}", "call_id": "call-1"}
            with self.subTest(error=type(failure).__name__), patch('apps.ai_production_import.erp_assistant._tools', return_value=toolbox), \
                 patch('apps.ai_production_import.erp_assistant.request_response', side_effect=[response(output=[call]), failure]), \
                 self.assertLogs('apps.ai_production_import.erp_assistant', level='INFO') as captured, \
                 self.assertRaises(type(failure)) as error:
                resolve_erp_matches(result=result, source=self._source(), credentials={}, request=object())
            self.assertIs(error.exception, failure)
            logs = "\n".join(captured.output)
            self.assertIn("failed phase=query round=2 calls=1", logs)
            self.assertIn("code=" + getattr(failure, "code", "INTERNAL_ERROR"), logs)
            self.assertNotIn("internal-business-sentinel", logs)


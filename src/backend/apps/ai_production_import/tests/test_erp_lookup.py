import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.ai_production_import.erp_lookup import (
    DEFINITIONS, ProductionAssistantTools, _required_fields, _selection,
)


MODULE = "apps.ai_production_import.erp_lookup"


def request():
    return SimpleNamespace(user=SimpleNamespace(is_authenticated=True), parser_context={"view": "original"}, method="POST")


def permission_view(allowed):
    permission = MagicMock()
    permission.has_permission.return_value = allowed
    return SimpleNamespace(get_permissions=lambda: [permission]), permission


def query_rows(rows):
    query = MagicMock()
    query.filter.return_value = query
    query.select_related.return_value = query
    query.order_by.return_value = query
    query.distinct.return_value = query
    query.__getitem__.side_effect = lambda key: rows[key]
    query.__iter__.side_effect = lambda: iter(rows)
    query.first.return_value = rows[0] if rows else None
    return query


def catalog_row(key=None):
    return SimpleNamespace(pk=key or str(uuid4()), category_key="HARDWARE", template_key="HARDWARE", name="铆钉",
                           spray_enabled=False, updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


class ProductionAssistantToolsTests(SimpleTestCase):
    def setUp(self):
        self.request = request()
        self.tools = ProductionAssistantTools(self.request)

    def test_function_schemas_are_strict_closed_objects(self):
        def check(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(value["additionalProperties"], False)
                    self.assertEqual(set(value["required"]), set(value["properties"]))
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        self.assertEqual(len(DEFINITIONS), 6)
        for item in self.tools.definitions:
            self.assertIs(item["strict"], True)
            check(item["parameters"])
        self.tools.definitions[0]["name"] = "changed"
        self.assertEqual(DEFINITIONS[0]["name"], "search_erp_materials")

    def test_unknown_tool_and_invalid_parameters_never_query(self):
        invalid = [
            ("write_database", {}), ([], {}),
            ("search_erp_materials", {"queries": []}),
            ("search_erp_materials", {"queries": [{"query": "铆钉", "category": "HARDWARE"}] * 13}),
            ("search_erp_materials", {"queries": [{"query": "铆钉", "category": "UNKNOWN"}]}),
            ("search_erp_materials", {"queries": [{"query": "a\x00b", "category": ""}]}),
            ("get_erp_materials", {"catalog_ids": ["invalid"]}),
            ("search_erp_attributes", {"queries": []}),
            ("search_erp_attributes", {"queries": [{"options_ref": "unknown", "field_key": "size", "query": ""}] * 13}),
            ("get_bom_history", {"bom_id": "invalid"}),
            ("get_production_crafts", {"query": "", "sql": "SELECT 1"}),
            ("search_production_history", {"query": "HT1", "limit": True}),
            ("search_production_history", {"query": "HT1", "limit": 11}),
        ]
        with patch(f"{MODULE}.catalog_list") as materials, patch(f"{MODULE}.accessible_boms") as boms:
            for name, arguments in invalid:
                with self.subTest(name=name, arguments=arguments):
                    self.assertIn("error", self.tools.execute(name, arguments))
            materials.assert_not_called()
            boms.assert_not_called()

    def test_denied_read_does_not_query_and_restores_real_request_context(self):
        view, permission = permission_view(False)
        original = self.request.parser_context
        with patch(f"{MODULE}._view", return_value=view), patch(f"{MODULE}.catalog_list") as lookup:
            result = self.tools.execute("search_erp_materials", {"queries": [{"query": "铆钉", "category": ""}]})
        self.assertEqual(result["error"], "FORBIDDEN")
        lookup.assert_not_called()
        permission.has_permission.assert_called_once_with(self.request, view)
        self.assertIs(view.request, self.request)
        self.assertIs(self.request.parser_context, original)

    def test_anonymous_request_cannot_query(self):
        self.request.user.is_authenticated = False
        with patch(f"{MODULE}.catalog_list") as lookup:
            result = self.tools.execute("search_erp_materials", {"queries": [{"query": "铆钉", "category": ""}]})
        self.assertEqual(result["error"], "FORBIDDEN")
        lookup.assert_not_called()

    def test_search_limits_results_and_omits_query_from_audit(self):
        view, _ = permission_view(True)
        rows = [SimpleNamespace(pk=uuid4()) for _ in range(21)]
        with (patch(f"{MODULE}._view", return_value=view), patch(f"{MODULE}.catalog_list", return_value=query_rows(rows)) as lookup,
                patch(f"{MODULE}.catalog_summary", side_effect=lambda row: {"id": str(row.pk)})):
            result = self.tools.execute("search_erp_materials", {"queries": [{"query": "私有材料名", "category": "HARDWARE"}]})
        lookup.assert_called_once_with(category="HARDWARE", query="私有材料名")
        self.assertEqual(len(result["results"][0]["materials"]), 20)
        self.assertTrue(result["results"][0]["has_more"])
        self.assertNotIn("私有材料名", json.dumps(self.tools.audit, ensure_ascii=False))

    def test_catalog_cache_contains_only_returned_real_candidates(self):
        catalog, missing = catalog_row(), str(uuid4())
        detail = {"id": catalog.pk, "base_warehouse_id": "private", "units": [], "values": [
            {"id": "option", "scope": "BASE", "field_key": "size", "value": "M5"}]}
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
              patch(f"{MODULE}.catalog_list", return_value=query_rows([catalog])),
              patch(f"{MODULE}.catalog_detail", return_value=detail)):
            result = self.tools.execute("get_erp_materials", {"catalog_ids": [catalog.pk, missing]})
        cached = self.tools.catalog_details[catalog.pk]
        self.assertEqual(result["not_found"], [missing])
        self.assertEqual(cached["catalog"]["base_warehouse_id"], "private")
        self.assertNotIn("base_warehouse_id", result["materials"][0]["catalog"])
        self.assertNotIn("values", result["materials"][0]["catalog"])
        self.assertEqual(cached["required_fields"]["any"], ["specification", "size", "thread"])
        self.assertEqual(result["templates"][0]["options"]["values"], [])
        self.assertEqual(cached["options"]["values"], [])
        ref = result["materials"][0]["options_ref"]
        self.assertEqual(self.tools._full_template_options[ref]["values"], detail["values"])

    def test_same_template_names_use_independent_metadata_and_candidates(self):
        first, second = catalog_row(), catalog_row()
        def detail(catalog):
            name = "甲" if catalog == first else "乙"
            return {"values": [{"id": name, "field_key": "size", "scope": "BASE", "value": name},
                               {"id": "off", "field_key": "size", "scope": "BASE", "value": "停用", "selectable": False}],
                    "units": [{"id": "link", "scope": "BASE", "unit_id": name, "unit_name": name},
                              {"id": "off", "scope": "BASE", "unit_id": "off", "unit_name": "停用", "selectable": False}]}
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
              patch(f"{MODULE}.catalog_list", return_value=query_rows([first, second])),
              patch(f"{MODULE}.catalog_detail", side_effect=detail)):
            arguments = {"catalog_ids": [first.pk, second.pk]}
            original = self.tools.execute("get_erp_materials", arguments)
            repeated = self.tools.execute("get_erp_materials", arguments)
            refs = [row["options_ref"] for row in original["materials"]]
            self.assertNotEqual(*refs)
            self.assertEqual(repeated["templates"], [])
            self.assertEqual(len(original["templates"]), 2)
            self.assertEqual(original["templates"][0]["options"]["units"], [{"id": "甲", "unit_name": "甲"}])
            self.assertNotIn("source", original["templates"][0]["options"]["fields"][0])
            self.assertNotIn("manage_url", original["templates"][0]["options"]["fields"][0])
            search = self.tools.execute("search_erp_attributes", {"queries": [
                {"options_ref": ref, "field_key": "size", "query": ""} for ref in refs]})
        self.assertEqual([[v["value"] for v in row["values"]] for row in search["results"]], [["甲"], ["乙"]])

    def test_failed_response_does_not_mark_template_as_sent(self):
        catalog = catalog_row()
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
              patch(f"{MODULE}.catalog_list", return_value=query_rows([catalog])),
              patch(f"{MODULE}.catalog_detail", return_value={"id": catalog.pk, "values": [], "units": []})):
            with patch(f"{MODULE}.MAX_RESPONSE_BYTES", 10):
                rejected = self.tools.execute("get_erp_materials", {"catalog_ids": [catalog.pk]})
            self.assertEqual(rejected["error"], "RESULT_TOO_LARGE")
            self.assertEqual(self.tools._sent_templates, set())
            self.assertEqual(self.tools._template_options, {})
            self.assertEqual(self.tools._full_template_options, {})
            self.assertEqual(self.tools.catalog_details, {})
            retried = self.tools.execute("get_erp_materials", {"catalog_ids": [catalog.pk]})
        self.assertEqual(len(retried["templates"]), 1)
        self.assertEqual(self.tools._sent_templates, {retried["materials"][0]["options_ref"]})

    def _load_materials(self, options, catalogs=None, *, spray_options=None):
        catalogs = catalogs or [catalog_row()]
        values, units = [], []
        for scope, source in (("BASE", options), ("SPRAY", spray_options or {})):
            values.extend({**row, "scope": scope} for row in source.get("values", []))
            units.extend({**row, "scope": scope, "unit_id": row["id"]} for row in source.get("units", []))
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
              patch(f"{MODULE}.catalog_list", return_value=query_rows(catalogs)),
              patch(f"{MODULE}.catalog_detail", return_value={"values": values, "units": units})):
            result = self.tools.execute("get_erp_materials", {"catalog_ids": [str(row.pk) for row in catalogs]})
        self.assertNotIn("error", result)
        self.base_ref = result["materials"][0]["options_ref"]
        self.spray_ref = result["materials"][0]["spray_options_ref"]
        return catalogs

    def test_enabled_tube_and_hardware_keep_separate_spray_candidates_per_name(self):
        base = {"values": [{"id": "base", "field_key": "color", "value": "黑色"}]}
        spray = {"values": [{"id": "spray", "field_key": "color", "value": "黑色亮光"}]}
        for category in ("TUBE", "HARDWARE"):
            with self.subTest(category=category):
                first, second = catalog_row(), catalog_row()
                for catalog in (first, second):
                    catalog.category_key = catalog.template_key = category
                    catalog.spray_enabled = True
                self._load_materials(base, [first, second], spray_options=spray)
                self.assertNotEqual(self.base_ref, self.spray_ref)
                with patch.object(self.tools, "_read_context", return_value=nullcontext()):
                    searched = self.tools.execute("search_erp_attributes", {"queries": [{
                        "options_ref": self.spray_ref, "field_key": "color", "query": "亮"}]})
                self.assertEqual([r["value"] for r in searched["results"][0]["values"]], ["黑色亮光"])
                self.assertEqual(self.tools.catalog_details[first.pk]["options"]["values"], [])
                self.assertEqual(self.tools.catalog_details[second.pk]["spray_options"]["values"], [])

    def test_disabled_or_unsupported_catalog_cannot_enable_spray_queries(self):
        for category, enabled in (("HARDWARE", False), ("PLASTIC", True)):
            with self.subTest(category=category, enabled=enabled):
                self.tools = ProductionAssistantTools(self.request)
                catalog = catalog_row()
                catalog.category_key = catalog.template_key = category
                catalog.spray_enabled = enabled
                options = {"fields": [{"key": "color", "kind": "text"}], "units": [], "values": []}
                self._load_materials(options, [catalog])
                self.assertIsNone(self.tools.catalog_details[catalog.pk]["spray_options"])
                result = self.tools.execute("search_erp_attributes", {"queries": [{
                    "options_ref": f"{category}/{category}/SPRAY", "field_key": "color", "query": ""}]})
                self.assertEqual(result["error"], "UNKNOWN_OPTIONS_REF")

    def test_spray_search_permission_and_oversized_response_do_not_expose_candidates(self):
        catalog = catalog_row()
        catalog.spray_enabled = True
        options = {"fields": [{"key": "color", "kind": "text"}], "units": [], "values": []}
        spray = {**options, "values": [{"id": "spray", "field_key": "color", "value": "黑色亮光", "parent_id": None}]}
        self._load_materials(options, [catalog], spray_options=spray)
        arguments = {"queries": [{"options_ref": self.spray_ref, "field_key": "color", "query": "亮"}]}
        denied, _ = permission_view(False)
        with patch(f"{MODULE}._view", return_value=denied):
            result = self.tools.execute("search_erp_attributes", arguments)
        self.assertEqual(result["error"], "FORBIDDEN")
        self.assertEqual(self.tools.catalog_details[catalog.pk]["spray_options"]["values"], [])
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            with patch(f"{MODULE}.MAX_RESPONSE_BYTES", 10):
                failed = self.tools.execute("search_erp_attributes", arguments)
            self.assertEqual(failed["error"], "RESULT_TOO_LARGE")
            self.assertEqual(self.tools.catalog_details[catalog.pk]["spray_options"]["values"], [])
            retried = self.tools.execute("search_erp_attributes", arguments)
            repeated = self.tools.execute("search_erp_attributes", arguments)
        self.assertEqual(retried, repeated)
        third = catalog_row()
        third.spray_enabled = True
        self._load_materials(options, [third], spray_options=spray)
        self.assertEqual(self.tools.catalog_details[third.pk]["spray_options"]["values"], [])
        self.assertEqual(self.tools.catalog_details[third.pk]["options"]["values"], [])

    def test_failed_spray_metadata_response_leaves_both_scopes_unavailable(self):
        catalog = catalog_row()
        catalog.spray_enabled = True
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
                patch(f"{MODULE}.catalog_list", return_value=query_rows([catalog])),
                patch(f"{MODULE}.catalog_detail", return_value={"id": catalog.pk, "values": [], "units": []}),
                patch(f"{MODULE}.MAX_RESPONSE_BYTES", 10)):
            result = self.tools.execute("get_erp_materials", {"catalog_ids": [catalog.pk]})
        self.assertEqual(result["error"], "RESULT_TOO_LARGE")
        self.assertEqual(self.tools.catalog_details, {})
        self.assertEqual(self.tools._template_options, {})
        self.assertEqual(self.tools._full_template_options, {})
        self.assertEqual(self.tools._sent_templates, set())
        result = self.tools.execute("search_erp_attributes", {"queries": [{
            "options_ref": "unknown-spray-ref", "field_key": "color", "query": "黑"}]})
        self.assertEqual(result["error"], "UNKNOWN_OPTIONS_REF")

    def test_attribute_query_rejects_unknown_ref_and_non_attribute_fields(self):
        self._load_materials({"fields": [{"key": "size", "kind": "text"}, {"key": "unit", "kind": "unit"}],
                              "values": [], "units": []})
        valid = {"options_ref": self.base_ref, "field_key": "size", "query": ""}
        invalid = [
            {**valid, "options_ref": "TUBE/TUBE/BASE"}, {**valid, "options_ref": []},
            {**valid, "field_key": "unknown"}, {**valid, "field_key": "unit"}, {**valid, "field_key": []},
            {**valid, "query": "x" * 101}, {**valid, "query": "a\x00b"}, {**valid, "query": 5},
        ]
        with patch(f"{MODULE}._view") as view:
            for item in invalid:
                with self.subTest(item=item):
                    result = self.tools.execute("search_erp_attributes", {"queries": [item]})
                    self.assertIn("error", result)
            view.assert_not_called()

    def test_attribute_search_rechecks_catalog_read_permission_with_cached_data(self):
        catalogs = self._load_materials({"fields": [{"key": "size", "kind": "text"}],
                                        "values": [{"id": "one", "field_key": "size", "value": "M5"}], "units": []})
        denied, permission = permission_view(False)
        original = self.request.parser_context
        with patch(f"{MODULE}._view", return_value=denied) as view:
            result = self.tools.execute("search_erp_attributes", {"queries": [{
                "options_ref": self.base_ref, "field_key": "size", "query": "M5"}]})
        self.assertEqual(result["error"], "FORBIDDEN")
        view.assert_called_once_with("materials", "retrieve")
        permission.has_permission.assert_called_once_with(self.request, denied)
        self.assertIs(self.request.parser_context, original)
        self.assertEqual(self.tools.catalog_details[catalogs[0].pk]["options"]["values"], [])

    def test_only_requested_catalog_receives_searched_values(self):
        options = {"fields": [{"key": "material", "kind": "text"}], "units": [{"id": "unit", "unit_name": "个"}],
                   "values": [{"id": "one", "field_key": "material", "value": "Q235", "parent_id": None},
                              {"id": "two", "field_key": "material", "value": "铝", "parent_id": None}]}
        first, second = self._load_materials(options, [catalog_row(), catalog_row()])
        for catalog in (first, second):
            self.assertEqual(self.tools.catalog_details[catalog.pk]["options"]["values"], [])
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            result = self.tools.execute("search_erp_attributes", {"queries": [{
                "options_ref": self.base_ref, "field_key": "material", "query": "Q235"}]})
        self.assertEqual([row["value"] for row in result["results"][0]["values"]], ["Q235"])
        ref = self.base_ref
        third = self._load_materials(options)[0]
        for catalog in (second, third):
            self.assertEqual(self.tools.catalog_details[catalog.pk]["options"]["values"], [])
        cached = self.tools.catalog_details[first.pk]["options"]
        self.assertEqual([row["value"] for row in cached["values"]], ["Q235"])
        self.assertEqual(cached["units"], options["units"])
        self.assertEqual(len(self.tools._full_template_options[ref]["values"]), 2)
        result["results"][0]["values"][0]["value"] = "response changed"
        self.assertEqual(self.tools.catalog_details[first.pk]["options"]["values"][0]["value"], "Q235")

    def test_repeated_attribute_search_deduplicates_but_keeps_parent_relations(self):
        options = {"fields": [{"key": "size", "kind": "text"}], "units": [], "values": [
            {"id": "same-id", "field_key": "size", "value": "16", "parent_id": "round"},
            {"id": "same-id", "field_key": "size", "value": "16", "parent_id": "oval"}]}
        catalog = self._load_materials(options)[0]
        arguments = {"queries": [{"options_ref": self.base_ref, "field_key": "size", "query": "16"}]}
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            first = self.tools.execute("search_erp_attributes", arguments)
            repeated = self.tools.execute("search_erp_attributes", arguments)
        self.assertEqual(first, repeated)
        self.assertEqual({row["parent_id"] for row in self.tools.catalog_details[catalog.pk]["options"]["values"]},
                         {"round", "oval"})

    def test_attribute_search_normalizes_text_prioritizes_exact_and_preserves_colors(self):
        options = {"fields": [{"key": key, "kind": "text"} for key in ("size", "color")], "units": [], "values": [
            {"id": "partial", "field_key": "size", "value": "M5×120", "parent_id": None},
            {"id": "exact", "field_key": "size", "value": "M5*12", "parent_id": None},
            {"id": "different-unit", "field_key": "size", "value": "1.2cm", "parent_id": None},
            {"id": "color", "field_key": "color", "value": "深碳灰色", "parent_id": None, "scope": "BASE",
             "product_color_id": "product-color", "color_card": "金牛", "color_code": "DS02", "color_name": "深碳灰色"}]}
        self._load_materials(options)
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            result = self.tools.execute("search_erp_attributes", {"queries": [
                {"options_ref": self.base_ref, "field_key": "size", "query": "  m５ × 12 "},
                {"options_ref": self.base_ref, "field_key": "size", "query": "12mm"},
                *[{"options_ref": self.base_ref, "field_key": "color", "query": query}
                  for query in ("d s 02", "深碳", "金牛")],
            ]})
        self.assertEqual([row["id"] for row in result["results"][0]["values"]], ["exact", "partial"])
        self.assertEqual(result["results"][1]["values"], [])
        for row in result["results"][2:]:
            color = row["values"][0]
            self.assertEqual(color["product_color_id"], "product-color")
            self.assertEqual(color["color_code"], "DS02")
            self.assertEqual(color["color_card"], "金牛")
            self.assertEqual(color["parent_id"], None)
            self.assertNotIn("scope", color)

    def test_attribute_search_limits_each_query_and_never_caches_hidden_matches(self):
        values = [{"id": str(index), "field_key": "size", "value": f"M5×{index}", "parent_id": None} for index in range(25)]
        values.append({"id": "exact", "field_key": "size", "value": "M5", "parent_id": None})
        catalog = self._load_materials({"fields": [{"key": "size", "kind": "text"}], "units": [], "values": values})[0]
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            result = self.tools.execute("search_erp_attributes", {"queries": [{
                "options_ref": self.base_ref, "field_key": "size", "query": "M5"}]})
        row = result["results"][0]
        self.assertEqual(len(row["values"]), 20)
        self.assertTrue(row["has_more"])
        self.assertEqual(row["values"][0]["id"], "exact")
        self.assertEqual(self.tools.catalog_details[catalog.pk]["options"]["values"], row["values"])

    def test_empty_attribute_query_lists_small_enum_without_crossing_fields(self):
        self._load_materials({"fields": [{"key": key, "kind": "text"} for key in ("size", "material")], "units": [],
                              "values": [{"id": "size", "field_key": "size", "value": "M5"},
                                         {"id": "material", "field_key": "material", "value": "Q235"}]})
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            result = self.tools.execute("search_erp_attributes", {"queries": [{
                "options_ref": self.base_ref, "field_key": "material", "query": ""}]})
        self.assertEqual([row["value"] for row in result["results"][0]["values"]], ["Q235"])
        self.assertFalse(result["results"][0]["has_more"])

    def test_failed_attribute_response_does_not_extend_visible_candidates(self):
        catalog = self._load_materials({"fields": [{"key": "size", "kind": "text"}], "units": [], "values": [
            {"id": "one", "field_key": "size", "value": "M5"},
            {"id": "two", "field_key": "size", "value": "M6"}]})[0]
        def arguments(query):
            return {"queries": [{"options_ref": self.base_ref, "field_key": "size", "query": query}]}
        with patch.object(self.tools, "_read_context", return_value=nullcontext()):
            self.tools.execute("search_erp_attributes", arguments("M5"))
            with patch(f"{MODULE}.MAX_RESPONSE_BYTES", 10):
                result = self.tools.execute("search_erp_attributes", arguments("M6"))
            self.assertEqual(result["error"], "RESULT_TOO_LARGE")
            self.assertEqual([row["value"] for row in self.tools.catalog_details[catalog.pk]["options"]["values"]], ["M5"])
            failed_batch = self.tools.execute("search_erp_attributes", {"queries": [
                arguments("M6")["queries"][0], {"options_ref": "unread", "field_key": "size", "query": "M6"}]})
            self.assertEqual(failed_batch["error"], "UNKNOWN_OPTIONS_REF")
            self.assertEqual([row["value"] for row in self.tools.catalog_details[catalog.pk]["options"]["values"]], ["M5"])
            retried = self.tools.execute("search_erp_attributes", arguments("M6"))
        self.assertNotIn("error", retried)
        self.assertEqual({row["value"] for row in self.tools.catalog_details[catalog.pk]["options"]["values"]}, {"M5", "M6"})

    def test_missing_catalog_permission_prevents_detail_cache(self):
        denied, _ = permission_view(False)
        catalog = SimpleNamespace(pk=uuid4())
        with (patch(f"{MODULE}._view", return_value=denied),
                patch(f"{MODULE}.catalog_list", return_value=query_rows([catalog])),
                patch(f"{MODULE}.catalog_detail") as detail):
            result = self.tools.execute("get_erp_materials", {"catalog_ids": [str(catalog.pk)]})
        self.assertEqual(result["error"], "FORBIDDEN")
        detail.assert_not_called()
        self.assertEqual(self.tools.catalog_details, {})

    def test_oversized_result_does_not_cache_unreturned_values(self):
        def too_large(arguments):
            self.tools._pending_catalogs["unreturned"] = {"catalog": {}}
            return {"materials": ["a" * 50]}
        with patch.object(self.tools, "_get_erp_materials", side_effect=too_large), patch(f"{MODULE}.MAX_RESPONSE_BYTES", 10):
            result = self.tools.execute("get_erp_materials", {})
        self.assertEqual(result["error"], "RESULT_TOO_LARGE")
        self.assertEqual(self.tools.catalog_details, {})

    def test_internal_errors_propagate_and_context_is_restored(self):
        view, _ = permission_view(True)
        original = self.request.parser_context
        with patch(f"{MODULE}._view", return_value=view), patch(f"{MODULE}.catalog_list", side_effect=RuntimeError("internal")):
            with self.assertRaisesRegex(RuntimeError, "internal"):
                self.tools.execute("search_erp_materials", {"queries": [{"query": "铆钉", "category": ""}]})
        self.assertIs(self.request.parser_context, original)
        self.assertEqual(self.tools.audit[-1]["status"], "INTERNAL_ERROR")

    def test_history_uses_actual_request_and_bom_read_context(self):
        view, _ = permission_view(True)
        seen = []
        def scoped(actual):
            seen.append((actual, actual.parser_context["view"]))
            return query_rows([])
        with patch(f"{MODULE}._view", return_value=view), patch(f"{MODULE}.accessible_boms", side_effect=scoped):
            result = self.tools.execute("get_bom_history", {"bom_id": str(uuid4())})
        self.assertEqual(result["error"], "NOT_FOUND")
        self.assertEqual(seen, [(self.request, view)])
        self.assertEqual(self.request.parser_context, {"view": "original"})

    def test_history_search_keeps_separate_read_permissions(self):
        denied, _ = permission_view(False)
        allowed, _ = permission_view(True)
        with (patch(f"{MODULE}._view", side_effect=[denied, allowed]),
                patch(f"{MODULE}.accessible_production_tasks") as tasks,
                patch(f"{MODULE}.accessible_boms", return_value=query_rows([])) as boms,
                patch(f"{MODULE}.search_boms", side_effect=lambda rows, query: rows)):
            result = self.tools.execute("search_production_history", {"query": "HT1", "limit": 3})
        tasks.assert_not_called()
        boms.assert_called_once_with(self.request)
        self.assertEqual(result["restricted"], ["production_tasks"])
        self.assertEqual(result["boms"], [])

    def test_history_task_scope_receives_explicit_read_permission(self):
        view, _ = permission_view(True)
        with (patch(f"{MODULE}._view", return_value=view),
                patch(f"{MODULE}.accessible_production_tasks", return_value=query_rows([])) as tasks,
                patch(f"{MODULE}.accessible_boms", return_value=query_rows([])),
                patch(f"{MODULE}.search_boms", side_effect=lambda rows, query: rows)):
            result = self.tools.execute("search_production_history", {"query": "HT1", "limit": 3})
        tasks.assert_called_once_with(self.request, permission="production_tasks.view_productiontask")
        self.assertEqual(result["restricted"], [])
        self.assertEqual(self.request.parser_context, {"view": "original"})

    def test_history_line_limit_and_source_whitelist(self):
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bom = SimpleNamespace(pk=uuid4(), production_task_id=uuid4(), production_task=SimpleNamespace(task_number="HT1"),
                              bom_number="B1", version_number=1, product_name_snapshot="椅", product_code_snapshot="C1",
                              specification_snapshot="50cm", status="CONFIRMED", updated_at=stamp, source_sheet_name="BOM")
        row = SimpleNamespace(pk=uuid4(), section=SimpleNamespace(title="五金件"), line_number=1, part_name="铆钉",
                              material="Q235", specification="M5", raw_material="Q235", unit="个", length_value="",
                              unit_consumption="2", hardness="", original_material_length="", component_kind="",
                              material_catalog_id=uuid4(), fabric_source_line_id=None, source_row_number=10,
                              material_selection_snapshot={"attributes": {"size": "M5", "phone": "secret"}, "unit_price": "99"},
                              notes="客户电话 secret", raw_values={"password": "secret"})
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
                patch(f"{MODULE}.accessible_boms", return_value=query_rows([bom])),
                patch(f"{MODULE}.BomLine.objects.filter", return_value=query_rows([row] * 151))):
            result = self.tools.execute("get_bom_history", {"bom_id": str(bom.pk)})
        self.assertEqual(len(result["lines"]), 150)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["lines"][0]["source"], {"sheet": "BOM", "row": 10})
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("unit_price", json.dumps(result))
        self.assertIn("不得用历史值覆盖", result["notice"])

    def test_crafts_return_exact_existing_identity_and_cache(self):
        craft = SimpleNamespace(pk=uuid4(), name="裁剪", craft_type="INTERNAL", plan_category="CUTTING", outsourcing_code=None)
        with (patch.object(self.tools, "_read_context", return_value=nullcontext()),
                patch(f"{MODULE}.Craft.objects.filter", return_value=query_rows([craft]))):
            result = self.tools.execute("get_production_crafts", {"query": ""})
        self.assertEqual(result["crafts"][0], {"id": str(craft.pk), "name": "裁剪", "craft_type": "INTERNAL", "code": "CUTTING"})
        self.assertEqual(self.tools.crafts[str(craft.pk)], result["crafts"][0])

    def test_required_fields_follow_current_bom_contract(self):
        self.assertEqual(_required_fields("TUBE"), {"all": ["material", "shape", "section_size", "thickness"], "any": []})
        self.assertEqual(_required_fields("FABRIC_SEMI"), {"all": [], "any": ["size", "model", "specification"]})
        self.assertEqual(_selection({"attributes": {"size": "10cm", "price": "99"}, "token": "secret"}),
                         {"attributes": {"size": "10cm"}})

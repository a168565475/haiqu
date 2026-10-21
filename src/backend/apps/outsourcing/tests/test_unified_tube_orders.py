"""统一列表新管材渠道：冻结摘要、最终凭证、权限与固定批量查询。"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.access_control.tests.test_resource_scopes import ScopedActorMixin
from apps.workshop_config.models import Craft

from ..models import OutsourcingFactory, TubeOutsourcingAction, TubeOutsourcingOrder
from .test_tube_receipts_api import TubeReceiptFixture
from .test_unified_orders import URL


class UnifiedTubeFixture(TubeReceiptFixture):
    def setUp(self):
        super().setUp()
        self.product_snapshot = {
            "product_name": "冻结管材椅", "product_number": "TUBE-LIST-PRODUCT",
            "item_number": "TUBE-LIST-ITEM", "color_name": "订单深蓝色",
        }
        self.schedule_product.product_snapshot = self.product_snapshot
        self.schedule_product.save(update_fields=["product_snapshot"])

    def rows(self, **filters):
        response = self.client.get(URL, filters, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def row(self, order, **filters):
        return next(row for row in self.rows(**filters)["data"] if row["row_key"] == f"TUBE:{order['id']}")

    def only_permissions(self, *names):
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])
        self.user.user_permissions.set([Permission.objects.get(content_type__app_label=name.split(".")[0],
            codename=name.split(".")[1]) for name in names])
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True)
class UnifiedTubeOrdersTests(UnifiedTubeFixture, APITestCase):
    def test_three_sources_keep_final_receipt_zero_and_shortage(self):
        self.receive(30)
        for source, received, kind, group in (("RAW_PIPE", "20", "RAW_PIPE", "RAW"),
            ("PUBLIC_SEMI", "18", "PUBLIC_SEMI", "TUBE_PUBLIC"), ("METAL", "0", "TUBE_METAL", "TUBE_METAL")):
            order = self.dispatched(source)
            self.receive_final(order, self.receipt_payload(order, received))
            row = self.row(order)
            self.assertEqual((row["record_type"], row["detail_access"], row["source_kind"], row["source_group"]),
                             ("TUBE", "TUBE", kind, group))
            self.assertEqual((row["status"], row["status_display"], row["receipt_state"]),
                             ("COMPLETED", "已结束", "RECORDED"))
            self.assertEqual(row["dispatched_quantities"], [{"quantity": "20", "unit": "支"}])
            self.assertEqual(row["returned_quantities"], [{"quantity": received, "unit": "支"}])
            self.assertEqual(row["shortage_quantities"], [{"quantity": str(20 - int(received)), "unit": "支"}])
            self.assertEqual(self.rows(status="COMPLETED", source_group=group)["meta"]["total"], 1)

    def test_pending_cancel_and_processing_do_not_replace_evidence_with_plan(self):
        pending = self.saved_order("METAL")
        row = self.row(pending)
        self.assertEqual((row["dispatched_quantities"], row["returned_quantities"], row["shortage_quantities"]), ([], [], []))
        self.assertEqual(row["receipt_state"], "NOT_RECEIVED")
        cancelled = self.act(pending, "cancel").data["data"]
        self.assertEqual(self.row(cancelled)["dispatched_quantities"], [])
        processing = self.dispatched("METAL")
        self.assertEqual(self.row(processing)["dispatched_quantities"], [{"quantity": "20", "unit": "支"}])
        self.assertEqual(self.row(processing)["receipt_state"], "NOT_RECEIVED")

    def test_completed_missing_or_inconsistent_evidence_is_unknown(self):
        order = self.dispatched("METAL")
        TubeOutsourcingOrder.objects.filter(pk=order["id"]).update(status="COMPLETED")
        row = self.row(order)
        self.assertEqual((row["receipt_state"], row["returned_quantities"], row["shortage_quantities"]), ("MISSING", [], []))
        TubeOutsourcingOrder.objects.filter(pk=order["id"]).update(status="PROCESSING")
        self.receive_final(order, self.receipt_payload(order, "0"))
        TubeOutsourcingAction.objects.filter(order_id=order["id"], kind="DISPATCH").update(snapshot={"quantity": 999})
        row = self.row(order)
        self.assertEqual((row["receipt_state"], row["dispatched_quantities"], row["returned_quantities"]), ("MISSING", [], []))

    def test_factory_filter_projects_actual_counts_but_keeps_whole_status(self):
        order = self.multi_part_order()
        payload = self.receipt_payload(order, "18")
        second_line = next(line for line in order["lines"] if line["factory_id"] != str(self.factory.pk))
        for line in payload["lines"]:
            if line["order_line_id"] == second_line["id"]:
                line["received_quantity"] = "0"
        self.receive_final(order, payload)
        total = self.row(order)
        self.assertEqual([total[field][0]["quantity"] for field in ("dispatched_quantities", "returned_quantities", "shortage_quantities")],
                         ["30", "18", "12"])
        for factory, expected in ((str(self.factory.pk), ["20", "18", "2"]), (second_line["factory_id"], ["10", "0", "10"])):
            row = self.row(order, factory_id=factory)
            self.assertEqual([row[field][0]["quantity"] for field in ("dispatched_quantities", "returned_quantities", "shortage_quantities")], expected)
            self.assertEqual((row["status"], row["status_display"], row["factory_count"]), ("COMPLETED", "已结束", 1))
            self.assertEqual(row["factory_allocation_count"], 1)
            self.assertEqual(row["factory_returned_quantity"], expected[1])
            self.assertIsNone(row["factory_remaining_quantity"])
            self.assertIsNone(row["factory_allocated_quantity"])
        self.assertEqual(self.rows(factory_id=str(uuid.uuid4()))["meta"]["total"], 0)

    def test_search_and_summary_use_frozen_product_without_live_source_reads(self):
        order = self.saved_order("METAL")
        self.product_line.product_name_snapshot = "当前已改名"
        self.product_line.save(update_fields=["product_name_snapshot"])
        with patch("apps.inventory.tube_processing_services.metal_component_limits", side_effect=AssertionError("动态报工")), \
             patch("apps.inventory.tube_outsourcing_limits.tube_source_context", side_effect=AssertionError("动态来源")), \
             patch("apps.inventory.tube_outsourcing_limits.prepare_tube_source", side_effect=AssertionError("动态额度")), \
             patch("apps.outsourcing.tube_selectors.saved_order_data", side_effect=AssertionError("完整详情")):
            row = self.row(order)
            for keyword in (*self.product_snapshot.values(), self.task.task_number, self.schedule.schedule_number, order["order_number"]):
                self.assertEqual(self.rows(search=keyword)["meta"]["total"], 1, keyword)
        self.assertEqual(row["product"], {**self.product_snapshot, "material": self.product_line.material_snapshot})
        self.assertEqual(row["product_count"], 1)
        self.assertEqual(self.rows(search="当前已改名")["meta"]["total"], 0)
        self.assertEqual(self.rows(production_task_id=str(self.task.pk), product_line_id=str(self.product_line.pk))["meta"]["total"], 1)
        self.assertEqual(self.rows(issue_id=str(self.issue_line.issue_id))["meta"]["total"], 0)

    def test_product_material_uses_snapshot_and_only_falls_back_when_key_is_missing(self):
        order = self.saved_order("METAL")
        self.product_line.material_snapshot = "当前产品材质"
        self.product_line.save(update_fields=["material_snapshot"])
        for snapshot, expected in ((self.product_snapshot, "当前产品材质"),
            ({**self.product_snapshot, "material": "冻结产品材质"}, "冻结产品材质"),
            ({**self.product_snapshot, "material": ""}, "")):
            with self.subTest(snapshot=snapshot):
                self.schedule_product.product_snapshot = snapshot
                self.schedule_product.save(update_fields=["product_snapshot"])
                self.assertEqual(self.row(order)["product"]["material"], expected)
                self.schedule_product.refresh_from_db()
                self.assertEqual(self.schedule_product.product_snapshot, snapshot)

    def test_inactive_factory_and_craft_keep_history_names(self):
        order = self.dispatched("METAL")
        saved_factory_name = self.row(order)["factory_names"]
        OutsourcingFactory.objects.filter(pk=self.factory.pk).update(status="DISABLED", name="当前改名厂")
        Craft.objects.filter(pk=self.spray.pk).update(status="INACTIVE")
        row = self.row(order)
        self.assertEqual(row["factory_names"], saved_factory_name)
        self.assertEqual(row["craft"]["name"], self.spray.name)

    def test_query_count_is_fixed_for_one_and_many_page_summaries_and_read_only(self):
        order = self.dispatched("METAL", "10")
        self.receive_final(order, self.receipt_payload(order, "0"))
        self.rows(source_kind="TUBE_METAL")
        before = self.receipt_snapshot()
        with CaptureQueriesContext(connection) as single:
            self.rows(source_kind="TUBE_METAL")
        self.assertEqual(before, self.receipt_snapshot())
        for _ in range(6):
            extra = self.dispatched("METAL", "10")
            self.receive_final(extra, self.receipt_payload(extra, "0"))
        before = self.receipt_snapshot()
        with CaptureQueriesContext(connection) as many:
            response = self.rows(source_kind="TUBE_METAL")
        self.assertEqual(response["meta"]["total"], 7)
        self.assertEqual(len(single), len(many))
        self.assertLess(len(many), 35)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in many))
        self.assertEqual(before, self.receipt_snapshot())

    def test_return_only_cannot_enter_unified_list_and_source_only_cannot_see_tubes(self):
        self.dispatched("METAL")
        self.only_permissions("outsourcing.confirm_return_outsourcingorder")
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.only_permissions("material_issues.view_metalprocessingsource")
        self.assertEqual(self.rows()["meta"]["total"], 0)
        self.only_permissions("outsourcing.view_outsourcingorder")
        self.assertEqual(self.rows()["meta"]["total"], 1)
        with override_settings(TUBE_OUTSOURCING_ENABLED=False):
            self.assertEqual(self.rows()["meta"]["total"], 0)

    def test_options_expose_independent_groups_and_reject_invalid_group(self):
        response = self.client.get(URL + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        options = response.data["data"]
        self.assertEqual({row["value"] for row in options["source_groups"]},
            {"RAW", "TUBE_PUBLIC", "TUBE_METAL", "CUTTING_PUBLIC", "SEWING", "OLD_METAL", "REWORK", "UNSELECTED"})
        self.assertTrue({"RAW", "METAL", "REWORK", "UNSELECTED"}.issubset({row["value"] for row in options["source_kinds"]}))
        self.assertEqual(self.client.get(URL, {"source_group": "METAL"}).status_code, 400)

    def test_options_include_all_supported_crafts_without_factory_and_keep_metal_scope(self):
        for code, name in (("EMBROIDERY", "刺绣"), ("SCREEN_PRINTING", "丝印"),
                           ("CUTTING", "裁剪"), ("SEWING", "车缝")):
            Craft.objects.get_or_create(outsourcing_code=code,
                defaults={"name": f"筛选测试{name}", "craft_type": "EXTERNAL", "status": "ACTIVE"})
        self.assertFalse(OutsourcingFactory.objects.filter(craft_links__craft__outsourcing_code="EMBROIDERY").exists())
        self.only_permissions("outsourcing.view_outsourcingorder")
        response = self.client.get(URL + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row["outsourcing_code"] for row in response.data["data"]["crafts"]},
                         {"POWDER_COATING", "SCREEN_PRINTING", "EMBROIDERY", "CUTTING", "SEWING"})
        self.only_permissions("material_issues.view_metalprocessingsource")
        response = self.client.get(URL + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row["outsourcing_code"] for row in response.data["data"]["crafts"]}, {"POWDER_COATING"})


@override_settings(TUBE_OUTSOURCING_ENABLED=True, PUBLIC_STOCK_FLOW_ENABLED=True,
    ACCESS_MANAGEMENT_ENABLED=True, MODULE_ACCESS_ENABLED=True, SALES_ACCESS_ENABLED=True,
    ACCESS_RESOURCE_SCOPES_ENABLED=True)
class UnifiedTubeScopedPermissionsTests(ScopedActorMixin, UnifiedTubeFixture, APITestCase):
    def test_options_keep_embroidery_craft_resource_scope(self):
        embroidery = Craft.objects.create(name="筛选权限刺绣", craft_type="EXTERNAL", outsourcing_code="EMBROIDERY")
        self.scoped_actor()
        self.grant("outsourcing.view_outsourcingorder", "CRAFT", [embroidery])
        response = self.client.get(URL + "options/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({row["id"] for row in response.data["data"]["crafts"]}, {str(embroidery.pk)})

    def test_frozen_order_craft_scope_survives_removed_plan_without_task_view(self):
        order = self.dispatched("METAL")
        self.scoped_actor()
        self.grant("outsourcing.view_outsourcingorder", "CRAFT", [self.spray])
        self.assertFalse(self.scope_user.has_perm("production_tasks.view_productiontask"))
        with patch("apps.production_scheduling.selectors.accessible_production_schedules", return_value=self.schedule_product.schedule.__class__.objects.none()):
            self.assertEqual(self.row(order)["detail_access"], "TUBE")

    def test_view_and_return_scopes_cannot_be_combined(self):
        self.dispatched("METAL")
        self.scoped_actor()
        unrelated = Craft.objects.create(name="列表无关工艺", craft_type="EXTERNAL", outsourcing_code="SEWING")
        self.grant("outsourcing.view_outsourcingorder", "CRAFT", [unrelated])
        self.grant("outsourcing.confirm_return_outsourcingorder", "CRAFT", [self.spray])
        self.assertEqual(self.rows()["meta"]["total"], 0)

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, APITestCase

from apps.boms.models import Bom, BomLine, BomSection
from apps.material_issues.models import (
    MaterialIssue, MaterialIssueAuditEvent, MaterialIssueLine, MetalProcessingExternalOrder,
    MetalProcessingOriginalHandoff, MetalProcessingRework, MetalProcessingSource,
    MetalProcessingUnsprayedReturn, OrderMaterialRequirement,
)
from apps.production_tasks.dashboard import source_context
from apps.production_tasks.tests.test_dashboard_api import DashboardFixture
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductCategory
from apps.workshop_config.models import Workshop

from ..api.unified_views import UnifiedOutsourcingOrderViewSet
from ..models import OutsourcingFactory, OutsourcingOrder, TubeOutsourcingLine, TubeOutsourcingOrder
from ..unified_selectors import unified_order_candidates, unified_order_sources


@override_settings(SALES_ACCESS_ENABLED=False, MODULE_ACCESS_ENABLED=False,
                   ACCESS_RESOURCE_SCOPES_ENABLED=False, TUBE_OUTSOURCING_ENABLED=True)
class DashboardUnifiedSourcesTests(DashboardFixture, APITestCase):
    """查询回归使用独占测试库实体，不依赖已变更的旧交接服务测试流程。"""

    def setUp(self):
        super().setUp()
        self.grant("outsourcing.view_outsourcingorder", "material_issues.view_metalprocessingsource")
        task = self.task("SOURCE", offset=1)
        schedule = self.schedule(task)
        plan = schedule.products.get()
        craft = plan.crafts.get().craft
        product = plan.product_line
        factory = OutsourcingFactory.objects.create(
            factory_number="DASH-FACTORY", name="看板测试加工厂", processing_type="喷塑",
            contact_name="测试联系人", contact_phone="test", address="测试地址",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        self.original = OutsourcingOrder.objects.create(
            order_number="DASH-ORIGINAL", schedule=schedule, craft=craft, craft_name_snapshot=craft.name,
            delivery_date=self.today - timedelta(days=30), status="PROCESSING", source_revision_hash="test",
            client_request_id=uuid4(), request_payload_hash="test",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        bom = Bom.objects.create(
            bom_number="DASH-BOM", production_task=task, product_line=product, creation_method="BLANK",
            status="VERIFIED", order_quantity=100, confirmed_at=timezone.now(), confirmed_by_employee=self.employee,
        )
        section = BomSection.objects.create(bom=bom, line_number=1, section_type="PROFILE", title="型材")
        bom_line = BomLine.objects.create(
            section=section, line_number=1, part_name="前脚管", cutting_length_mm=500, pieces_per_product=2,
            pieces_per_bar=10, raw_bar_length_m=6, suggested_bar_count=20, suggested_purchase_meters=120,
        )
        category = ProductCategory.objects.create(category_name="看板测试管材", item_type="MATERIAL")
        raw = RawMaterialInformation.objects.create(
            material_number="DASH-RAW", item_type="MATERIAL", category=category, material_name="测试原管",
            specification="20*1.0*6000", unit=self.unit, warehouse_number="DASH-WH", warehouse_name="测试原料仓",
        )
        requirement = OrderMaterialRequirement.objects.create(
            production_task=task, product_line=product, component_identity=bom_line.component_identity,
            raw_material=raw, unit=self.unit, line_type="RAW", section_code="PROFILE", measurement_kind="PIPE",
            pieces_per_bar=10, raw_bar_length_m=6, required_quantity=200, internal_issued_quantity=20,
            source_revision_hash="test",
        )
        workshop, _ = Workshop.objects.get_or_create(name="金工车间")
        issue = MaterialIssue.objects.create(
            issue_number="DASH-ISSUE", client_request_id=uuid4(), request_payload_hash="test",
            production_task=task, product_line=product, workshop=workshop, status="ISSUED",
            created_by_employee=self.employee, updated_by_employee=self.employee,
            issued_by_employee=self.employee, issued_at=timezone.now(),
        )
        MaterialIssueAuditEvent.objects.create(
            issue=issue, action="CREATED", issue_version=1, actor_employee=self.employee,
            snapshot={"plan_source": {"plan_category": "METAL"}},
        )
        self.line = MaterialIssueLine.objects.create(
            issue=issue, line_number=1, requirement=requirement, line_type="RAW", raw_material=raw, unit=self.unit,
            section_code_snapshot="PROFILE", material_number_snapshot=raw.material_number,
            material_name_snapshot=raw.material_name, unit_snapshot=self.unit.unit_name,
            requested_quantity=20, issued_quantity=20,
            conversion_snapshot={"kind": "PIPE", "component_identity": str(bom_line.component_identity),
                                 "product_line_id": str(product.pk), "raw_material_id": str(raw.pk),
                                 "bom_line_id": str(bom_line.pk), "bom_id": str(bom.pk),
                                 "pieces_per_bar": 10, "raw_bar_length_m": "6", "source_revision_hash": "test"},
        )
        source = MetalProcessingSource.objects.create(
            issue_line=self.line, source_snapshot={}, source_hash="test", issued_pieces=20,
            completed_pieces=20, dispatched_pieces=10,
        )
        handoff = MetalProcessingOriginalHandoff.objects.create(
            source=source, original_order=self.original, factory=factory, handoff_pieces=10,
            handoff_date=self.today, actor_employee=self.employee, request_id=uuid4(), request_payload_hash="test",
        )
        returned = MetalProcessingUnsprayedReturn.objects.create(
            original_handoff=handoff, returned_pieces=5, received_by_employee=self.employee,
            storage_location="测试暂存架", return_date=self.today, request_id=uuid4(), request_payload_hash="test",
        )
        rework = MetalProcessingRework.objects.create(
            unsprayed_return=returned, source=source, completed_pieces=5, completion_date=self.today,
            actor_employee=self.employee, request_id=uuid4(), request_payload_hash="test",
        )
        self.rework = MetalProcessingExternalOrder.objects.create(
            order_number="DASH-REWORK", rework=rework, source=source, original_return=returned,
            factory=factory, craft=craft, allocated_pieces=5, handoff_pieces=5, status="PROCESSING",
            client_request_id=uuid4(), request_payload_hash="test",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        self.tube = TubeOutsourcingOrder.objects.create(
            order_number="DASH-TUBE", schedule_product=plan, product_line=product, bom=bom, craft=craft,
            source_kind="METAL", planned_dispatch_date=self.today, expected_return_date=self.today,
            client_request_id=uuid4(), request_payload_hash="test", source_revision_hash="test",
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        TubeOutsourcingLine.objects.create(
            order=self.tube, bom_line=bom_line, component_identity=bom_line.component_identity,
            factory=factory, quantity=5, snapshot={"factory_name": factory.name},
        )

    def request(self, user=None):
        request = Request(APIRequestFactory().get("/api/v1/unified-outsourcing-orders/"))
        request.user = user or self.user
        request.employee = self.employee
        return request

    def test_extracted_queries_preserve_three_source_identities_and_filters(self):
        request = self.request()
        with source_context(request, UnifiedOutsourcingOrderViewSet):
            originals, reworks, tubes = unified_order_sources(request, {})
            self.assertEqual(set(originals.values_list("pk", flat=True)), {self.original.pk})
            self.assertEqual(set(reworks.values_list("pk", flat=True)), {self.rework.pk})
            self.assertEqual(set(tubes.values_list("pk", flat=True)), {self.tube.pk})
            expected = {(row["id"], row["record_type"]) for row in unified_order_candidates(request, {})}
            actual = {(row["id"], row["record_type"]) for query in (originals, reworks, tubes)
                      for row in query.values("id", "record_type")}
            self.assertEqual(actual, expected)
            self.assertEqual({kind for _, kind in actual}, {"ORIGINAL", "REWORK", "TUBE"})
            originals, reworks, tubes = unified_order_sources(request, {"source_kind": "REWORK"})
            self.assertFalse(originals.exists())
            self.assertEqual(list(reworks.values_list("pk", flat=True)), [self.rework.pk])
            self.assertFalse(tubes.exists())

    def test_metal_only_reader_keeps_source_projection_and_unknown_rework_deadline(self):
        self.user.user_permissions.set([Permission.objects.get(
            content_type__app_label="material_issues", codename="view_metalprocessingsource",
        )])
        user = get_user_model().objects.get(pk=self.user.pk)
        request = self.request(user)
        with source_context(request, UnifiedOutsourcingOrderViewSet):
            originals, reworks, tubes = unified_order_sources(request, {})
            self.assertEqual(set(originals.values_list("unified_access", flat=True)), {"METAL"})
            self.assertEqual(list(reworks.values_list("pk", flat=True)), [self.rework.pk])
            self.assertFalse(tubes.exists())
        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/production-dashboard/", {"days": 3})
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data["data"]["sections"]["outsourcing"]["data"]
        self.assertEqual(data["pending_count"], 2)
        self.assertEqual(data["overdue_count"], 0)
        original = next(row for row in data["items"] if row["row_key"].startswith("ORIGINAL:"))
        self.assertIsNone(original["delivery_date"])
        self.assertTrue(original["href"].endswith("?view=metal"))
        row = next(row for row in data["items"] if row["row_key"].startswith("REWORK:"))
        self.assertIsNone(row["delivery_date"])
        self.assertEqual(row["receipt_state"], "UNKNOWN")
        with patch("apps.outsourcing.unified_selectors._source_lines", return_value=MaterialIssueLine.objects.none()):
            response = self.client.get("/api/v1/production-dashboard/")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["data"]["sections"]["outsourcing"]["data"]["pending_count"], 0)

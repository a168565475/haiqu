"""采购申请数量的真实数据库回归；只复用准备方法，不继承旧测试类。"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.boms.models import Bom, BomCreationMethod, BomLine, BomSection, BomStatus
from apps.organizations.models import (
    EmployeeOrganizationAssignment, EmployeeRoleAssignment, OrganizationUnit, RoleProfile,
)
from apps.procurement import purchase_request_services as services
from apps.procurement.api.purchase_request_serializers import PurchaseRequestSerializer
from apps.procurement.models import (
    PurchaseAllocationStatus, PurchaseRequest, PurchaseRequestAllocation,
    PurchaseRequestLine, PurchaseRequestStatus,
)
from . import test_purchase_request_flow as flow_fixtures


class PurchaseRequestQuantityTests(APITestCase):
    _confirmed_order = flow_fixtures.PurchaseRequestFlowApiTests._confirmed_order
    _ready_production_order = flow_fixtures.PurchaseRequestFlowApiTests._ready_production_order
    test_original_confirmed_bom_to_supplier_order_flow = (
        flow_fixtures.PurchaseRequestFlowApiTests.test_confirmed_bom_to_purchase_request_and_one_supplier_order
    )

    def setUp(self):
        flow_fixtures.PurchaseRequestFlowApiTests.setUp(self)
        effective_from = timezone.now() - timedelta(days=1)
        # 原流程复用同一员工担任业务、计划和跟单，补齐当前候选范围要求。
        for code, name in [("DEPT_BUSINESS", "业务部"), ("DEPT_PRODUCTION", "生产部")]:
            department, _ = OrganizationUnit.objects.get_or_create(unit_code=code, defaults={"unit_name": name})
            EmployeeOrganizationAssignment.objects.create(
                employee=self.employee, organization_unit=department, effective_from=effective_from,
            )
        role, _ = RoleProfile.objects.get_or_create(role_code="MERCHANDISER", defaults={
            "display_name": "跟单",
            "auth_group": Group.objects.create(name="purchase-request-quantity-merchandiser"),
        })
        EmployeeRoleAssignment.objects.create(
            employee=self.employee, role_profile=role, effective_from=effective_from,
        )

    def make_request(self, quantities):
        production = self._ready_production_order(self._confirmed_order())
        product_line = self.product.production_task_lines.get(pk=production.data["data"]["products"][0]["id"])
        bom = Bom.objects.create(
            bom_number="BOM-PR-QUANTITY-001-V1", production_task_id=production.data["data"]["id"],
            product_line=product_line, version_number=1, creation_method=BomCreationMethod.BLANK,
            status=BomStatus.VERIFIED, product_number_snapshot=self.product.product_number,
            product_code_snapshot=self.product.product_code, product_name_snapshot=self.product.product_name,
            specification_snapshot=self.product.specification,
            product_category_snapshot=self.product.category.category_name, order_quantity=Decimal("10"),
            confirmed_by_employee=self.employee, confirmed_at=timezone.now(),
            created_by_employee=self.employee, updated_by_employee=self.employee,
        )
        section = BomSection.objects.create(bom=bom, line_number=1, section_type="FABRIC", title="面料类")
        for number in range(1, len(quantities) + 1):
            BomLine.objects.create(section=section, line_number=number, part_name=f"数量测试面料{number}",
                                   specification="600D", unit="米", total_purchase_quantity="12")
        response = self.client.post("/api/v1/purchase-requests/", {"bom_id": str(bom.pk)}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        purchase_request = PurchaseRequest.objects.get(pk=response.data["data"]["id"])
        lines = list(purchase_request.lines.order_by("line_number", "id"))
        for line, quantity in zip(lines, quantities):
            line.actual_request_quantity = Decimal(quantity) if quantity is not None else None
            line.required_date = timezone.localdate()
            line.difference_reason = "隔离测试数量依据"
            line.suggested_supplier = self.supplier
            line.save()
        return purchase_request, lines, response["ETag"]

    def allocation(self, line, quantity, status=PurchaseAllocationStatus.DRAFT):
        return PurchaseRequestAllocation.objects.create(
            purchase_request_line=line, supplier=self.supplier,
            procurement_batch_number="PC-QUANTITY-TEST", quantity=Decimal(quantity),
            expected_arrival_date=timezone.localdate(), status=status, created_by_employee=self.employee,
        )

    def contextual(self, purchase_request):
        return services.purchase_requests_with_context(PurchaseRequest.objects.filter(pk=purchase_request.pk)).get()

    def test_context_serializes_multiple_lines_without_queries_and_preserves_quantity_strings(self):
        purchase_request, lines, _ = self.make_request(["10.5000", None, "2.0000", "1.0000"])
        self.allocation(lines[0], "1.2345")
        self.allocation(lines[0], "1.2345")
        self.allocation(lines[0], "2.3456", PurchaseAllocationStatus.ORDERED)
        self.allocation(lines[0], "5.5555", PurchaseAllocationStatus.CANCELLED)
        self.allocation(lines[2], "1.1111", PurchaseAllocationStatus.CANCELLED)
        # 历史超分配数据只能显示零剩余；不能因本次读取优化返回负数。
        self.allocation(lines[3], "1.5000")
        contextual = self.contextual(purchase_request)
        with self.assertNumQueries(0):
            payload = PurchaseRequestSerializer(contextual).data
        rows = payload["lines"]
        self.assertEqual([row["line_number"] for row in rows], [1, 2, 3, 4])
        self.assertEqual([(row["allocated_quantity"], row["remaining_quantity"]) for row in rows],
                         [("4.8146", "5.6854"), ("0", "0"), ("0", "2.0000"), ("1.5000", "0")])
        self.assertIsNone(rows[1]["actual_request_quantity"])
        self.assertEqual(rows[0]["actual_request_quantity"], "10.5000")
        self.assertEqual({item["status"] for item in rows[0]["allocations"]}, {"DRAFT", "ORDERED", "CANCELLED"})
        self.assertTrue(all(item["supplier_name"] == self.supplier.supplier_name for item in rows[0]["allocations"]))
        self.assertEqual(rows[0]["suggested_supplier_name"], self.supplier.supplier_name)

    def test_snapshot_uses_one_fresh_query_after_allocations_change(self):
        purchase_request, lines, _ = self.make_request(["3.0000", "4.0000"])
        contextual = self.contextual(purchase_request)
        with self.assertNumQueries(1):
            before = services._request_snapshot(contextual)
        self.assertEqual([row["allocated_quantity"] for row in before["lines"]], ["0", "0"])
        first = self.allocation(lines[0], "1.2345")
        self.allocation(lines[1], "2.3456", PurchaseAllocationStatus.ORDERED)
        with self.assertNumQueries(1):
            after = services._request_snapshot(contextual)
        self.assertEqual([(row["allocated_quantity"], row["remaining_quantity"]) for row in after["lines"]],
                         [("1.2345", "1.7655"), ("2.3456", "1.6544")])
        first.status = PurchaseAllocationStatus.CANCELLED
        first.save(update_fields=["status", "updated_at"])
        with self.assertNumQueries(1):
            cancelled = services._request_snapshot(contextual)
        self.assertEqual(cancelled["lines"][0]["allocated_quantity"], "0")
        self.assertEqual(cancelled["lines"][0]["remaining_quantity"], "3.0000")

    def test_status_refresh_uses_current_totals_and_plain_instances_stay_live(self):
        purchase_request, lines, _ = self.make_request(["1.0000", "2.0000", "3.0000"])
        purchase_request.status = PurchaseRequestStatus.SUBMITTED
        purchase_request.save(update_fields=["status", "updated_at"])
        contextual = self.contextual(purchase_request)
        plain_line = PurchaseRequestLine.objects.get(pk=lines[0].pk)
        self.assertEqual(plain_line.allocated_quantity, Decimal("0"))
        with self.assertNumQueries(2):
            services._refresh_allocation_status(contextual)
        self.assertEqual(contextual.status, PurchaseRequestStatus.ALLOCATING)
        allocations = [self.allocation(line, quantity) for line, quantity in zip(lines, ["1.0000", "2.0000", "3.0000"])]
        self.assertEqual(plain_line.allocated_quantity, Decimal("1.0000"))
        with self.assertNumQueries(2):
            services._refresh_allocation_status(contextual)
        contextual.refresh_from_db()
        self.assertEqual(contextual.status, PurchaseRequestStatus.FULLY_ALLOCATED)
        contextual = self.contextual(purchase_request)
        allocations[0].status = PurchaseAllocationStatus.CANCELLED
        allocations[0].save(update_fields=["status", "updated_at"])
        self.assertEqual(plain_line.allocated_quantity, Decimal("0"))
        with self.assertNumQueries(2):
            services._refresh_allocation_status(contextual)
        contextual.refresh_from_db()
        self.assertEqual(contextual.status, PurchaseRequestStatus.ALLOCATING)

    def test_allocate_cancel_etags_and_stale_read_object_cannot_bypass_live_limit(self):
        purchase_request, lines, created_etag = self.make_request(["3.0000"])
        base_url = f"/api/v1/purchase-requests/{purchase_request.pk}/"
        updated = self.client.patch(base_url, {"lines": [{
            "id": str(lines[0].pk), "actual_request_quantity": "3.0000",
            "difference_reason": "本期只申请三米", "required_date": timezone.localdate().isoformat(),
            "suggested_supplier_id": str(self.supplier.pk),
        }]}, format="json", HTTP_IF_MATCH=created_etag)
        self.assertEqual(updated.status_code, 200, updated.data)
        submitted = self.client.post(base_url + "submit/", {}, format="json", HTTP_IF_MATCH=updated["ETag"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        stale_line = list(self.contextual(purchase_request).lines.all())[0]
        self.assertEqual(stale_line.allocated_quantity, Decimal("0"))
        data = {"purchase_request_line_id": str(lines[0].pk), "supplier_id": str(self.supplier.pk),
                "procurement_batch_number": "PC-QUANTITY-API", "quantity": "2.0000",
                "expected_arrival_date": timezone.localdate().isoformat()}
        first = self.client.post(base_url + "allocate/", data, format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(first.status_code, 201, first.data)
        with self.assertRaises(ValidationError):
            services.allocate_purchase_request_line(
                line=stale_line, actor_employee=self.employee,
                validated_data={"supplier": self.supplier, "procurement_batch_number": "PC-QUANTITY-STALE",
                                "quantity": Decimal("1.0001"), "expected_arrival_date": timezone.localdate()},
                request=SimpleNamespace(headers={"If-Match": first["ETag"]}, META={}),
            )
        self.assertEqual(PurchaseRequestAllocation.objects.filter(purchase_request_line=lines[0]).count(), 1)
        stale_etag = self.client.post(base_url + "allocate/", {**data, "quantity": "1.0000"},
                                     format="json", HTTP_IF_MATCH=submitted["ETag"])
        self.assertEqual(stale_etag.status_code, 412, stale_etag.data)
        second = self.client.post(base_url + "allocate/", {**data, "quantity": "1.0000"},
                                 format="json", HTTP_IF_MATCH=first["ETag"])
        self.assertEqual(second.status_code, 201, second.data)
        full = self.client.get(base_url)
        self.assertEqual(full.status_code, 200, full.data)
        self.assertEqual(full.data["data"]["status"], PurchaseRequestStatus.FULLY_ALLOCATED)
        self.assertEqual(full.data["data"]["lines"][0]["remaining_quantity"], "0.0000")
        cancelled = self.client.post(base_url + "cancel-allocation/",
            {"allocation_id": first.data["data"]["id"], "reason": "调整本期分配"},
            format="json", HTTP_IF_MATCH=second["ETag"])
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        partial = self.client.get(base_url)
        self.assertEqual(partial.status_code, 200, partial.data)
        self.assertEqual(partial.data["data"]["status"], PurchaseRequestStatus.ALLOCATING)
        self.assertEqual(partial.data["data"]["lines"][0]["allocated_quantity"], "1.0000")
        self.assertEqual(partial.data["data"]["lines"][0]["remaining_quantity"], "2.0000")

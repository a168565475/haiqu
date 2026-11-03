"""在旧表结构写入隔离夹具，验证总单迁移不改写既有履约记录。"""
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from apps.core.api.concurrency import etag_for_instance
from apps.procurement.tests import test_purchase_order_api as fixtures

from .group_test_fixtures import ensure_group_test_reference_data


class PurchaseGroupLegacyMigrationTests(TransactionTestCase):
    make_task = fixtures.PurchaseOrderApiTests.make_task
    make_product_line = fixtures.PurchaseOrderApiTests.make_product_line
    make_bom = fixtures.PurchaseOrderApiTests.make_bom

    def setUp(self):
        ensure_group_test_reference_data()
        fixtures.PurchaseOrderApiTests.setUp(self)
        self.task = self.make_task("GROUP-MIGRATION")
        self.product_line = self.make_product_line(self.task)
        self.bom, self.bom_line = self.make_bom(
            self.product_line, section_type="ACCESSORY", budget_quantity="999",
        )
        self.saved_at = timezone.now() - timedelta(days=30)

    @contextmanager
    def legacy_schema(self):
        executor = MigrationExecutor(connection)
        final_targets = executor.loader.graph.leaf_nodes()
        old_targets = [node for node in final_targets if node[0] != "procurement"]
        old_targets.append(("procurement", "0023_purchase_orders_per_product"))
        try:
            executor.migrate(old_targets)
            yield executor.loader.project_state(old_targets).apps
        finally:
            # 即使断言失败也恢复测试库结构，避免影响随后串行执行的其他测试。
            MigrationExecutor(connection).migrate(final_targets)

    def make_order(self, old_apps, number="CGDD2026092901", **overrides):
        values = {
            "order_number": number, "production_task_id": self.task.pk,
            "production_task_number_snapshot": self.task.task_number,
            "sales_order_number_snapshot": self.task.order_number,
            "customer_name_snapshot": "迁移测试客户快照", "source_revision": "legacy-source-v1",
            "currency_id": self.cny.pk, "currency_code_snapshot": "CNY",
            "status": "COMPLETED", "total_amount": Decimal("240"),
            "completed_at": self.saved_at, "completed_by_employee_id": self.employee.pk,
            "completion_remark": "历史部分到货后关闭履约", "created_by_employee_id": self.employee.pk,
        }
        values.update(overrides)
        model = old_apps.get_model("procurement", "PurchaseOrder")
        order = model.objects.create(**values)
        model.objects.filter(pk=order.pk).update(created_at=self.saved_at, updated_at=self.saved_at)
        return order

    def make_line(self, old_apps, order, number=1, **overrides):
        values = {
            "purchase_order_id": order.pk, "line_number": number,
            "bom_id": self.bom.pk, "bom_line_id": self.bom_line.pk,
            "source_bom_line_id_snapshot": self.bom_line.pk if number == 1 else uuid4(),
            "product_line_id_snapshot": self.product_line.pk,
            "bom_number_snapshot": self.bom.bom_number,
            "product_number_snapshot": "LEGACY-PRODUCT", "product_name_snapshot": "历史产品名称",
            "section_type_snapshot": "ACCESSORY", "section_title_snapshot": "配件类",
            "part_name_snapshot": "不同于库存主档品名的部件", "specification_snapshot": "保存时规格",
            "raw_material_snapshot": self.inventory_material.material_number,
            "material_attributes_snapshot": {"color": "保存时颜色"}, "calculation_snapshot": {},
            "required_quantity": Decimal("100"), "source_quantity_field": "budget_quantity",
            "source_quantity_text": "100", "source_unit_text": "PCS", "quantity_parse_status": "READY",
            "supplier_id": self.supplier.pk, "supplier_number_snapshot": self.supplier.supplier_number,
            "supplier_name_snapshot": "历史供应商名称", "supplier_categories_snapshot": ["TUBE"],
            "delivery_date": self.saved_at.date(), "actual_purchase_quantity": Decimal("120"),
            "unit_price": Decimal("2"), "amount": Decimal("240"),
        }
        values.update(overrides)
        model = old_apps.get_model("procurement", "PurchaseOrderLine")
        line = model.objects.create(**values)
        model.objects.filter(pk=line.pk).update(created_at=self.saved_at, updated_at=self.saved_at)
        return line

    @staticmethod
    def saved_rows(*objects):
        return [
            (obj._meta.app_label, obj._meta.model_name, obj.pk,
             type(obj).objects.values().get(pk=obj.pk))
            for obj in objects
        ]

    def assert_saved_rows_unchanged(self, rows, registry=apps):
        for app_label, model_name, pk, before in rows:
            with self.subTest(model=model_name, pk=pk):
                after = registry.get_model(app_label, model_name).objects.values(*before).get(pk=pk)
                self.assertEqual(after, before)

    def make_fulfilment(self, old_apps, order, line):
        def create(app_label, model_name, **values):
            return old_apps.get_model(app_label, model_name).objects.create(**values)

        warehouse = create("inventory", "Warehouse", warehouse_number="MIGRATION-ONLY",
                           warehouse_name="迁移测试材料仓", warehouse_type="MATERIAL")
        zone = create("inventory", "WarehouseZone", warehouse=warehouse, zone_name="迁移测试区")
        inbound = create("inventory", "MaterialInbound", inbound_number="MIGRATION-IN-01",
                         purchase_order=order, status="CONFIRMED", received_by_employee_id=self.employee.pk,
                         quality_confirmed_by_employee_id=self.employee.pk, quality_confirmed_at=self.saved_at)
        inbound_values = {
            "purchase_order_line": line, "raw_material_information_id": self.inventory_material.pk,
            "zone": zone, "received_quantity": Decimal("100"), "return_quantity": Decimal("20"),
            "accepted_quantity": Decimal("80"), "purchase_order_number_snapshot": order.order_number,
            "production_task_number_snapshot": self.task.task_number, "bom_number_snapshot": self.bom.bom_number,
            "product_name_snapshot": "历史产品名称", "section_type_snapshot": "ACCESSORY",
            "section_title_snapshot": "配件类", "part_name_snapshot": "历史部件名称",
            "source_unit_text_snapshot": "PCS", "purchased_quantity_snapshot": Decimal("120"),
        }
        inbound_line = create("inventory", "MaterialInboundLine", inbound=inbound, **inbound_values)
        pending = create("inventory", "MaterialInbound", inbound_number="MIGRATION-IN-02",
                         purchase_order=order, status="PENDING_QUALITY", received_by_employee_id=self.employee.pk)
        pending_line = create("inventory", "MaterialInboundLine", inbound=pending,
                              **{**inbound_values, "received_quantity": Decimal("20"),
                                 "return_quantity": Decimal("0"), "accepted_quantity": Decimal("20")})
        returned = create("procurement", "PurchaseReturn", return_number="MIGRATION-RETURN-01",
                          purchase_order=order, inbound=inbound, supplier_id=self.supplier.pk,
                          supplier_number_snapshot=self.supplier.supplier_number,
                          supplier_name_snapshot="历史供应商名称", generated_by_employee_id=self.employee.pk,
                          status="COMPLETED", confirmed_by_employee_id=self.employee.pk,
                          confirmed_at=self.saved_at, completed_by_employee_id=self.employee.pk,
                          completed_at=self.saved_at)
        return_line = create("procurement", "PurchaseReturnLine", return_order=returned,
                             inbound_line=inbound_line, quantity=Decimal("20"))
        template = create("procurement", "PurchaseContractTemplate", template_code="MIGRATION-ONLY",
                          template_name="迁移合同测试模板")
        version = create("procurement", "PurchaseContractTemplateVersion", template=template,
                         version_number=1, content_config={"terms": "历史合同条款"})
        sheet = create("procurement", "SupplierPurchaseSheet", purchase_order=order,
                       supplier_id=self.supplier.pk, supplier_number_snapshot=self.supplier.supplier_number,
                       supplier_name_snapshot="历史供应商名称", sheet_number=order.order_number,
                       template_version=version, status="PUBLISHED", total_amount=Decimal("240"),
                       published_at=self.saved_at, published_by_employee_id=self.employee.pk,
                       content_snapshot={"lines": [{"source_purchase_order_line_id": str(line.pk), "quantity": "120"}]})
        balance = create("inventory", "MaterialStockBalance", raw_material_id=self.inventory_material.pk,
                         unit_id=self.inventory_material.unit_id, zone=zone, quantity=Decimal("80"))
        movement = create("inventory", "MaterialStockMovement", balance=balance, direction="IN",
                          quantity=Decimal("80"), before_quantity=Decimal("0"), after_quantity=Decimal("80"),
                          source_type="MATERIAL_INBOUND", source_id=inbound.pk, source_line_id=inbound_line.pk,
                          production_task_id=self.task.pk, actor_employee_id=self.employee.pk,
                          occurred_at=self.saved_at, snapshot={"purchase_order_id": str(order.pk)})
        audit = create("audit", "AuditLog", object_type="PURCHASE_ORDER", object_id=order.pk,
                       context_type="PRODUCTION_TASK", context_id=self.task.pk, action="COMPLETED",
                       actor_employee_id=self.employee.pk, occurred_at=self.saved_at,
                       after_data={"order_number": order.order_number, "status": "COMPLETED"})
        return self.saved_rows(order, line, inbound, inbound_line, pending, pending_line,
                               returned, return_line, template, version, sheet, balance, movement, audit)

    def test_forward_preserves_fulfilment_and_number_only_identity_can_append_batch(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission

        from apps.inventory.models import MaterialInboundLine, MaterialStockBalance
        from apps.procurement.group_selectors import purchase_group_progress
        from apps.procurement.group_services import create_purchase_batch
        from apps.procurement.material_receipt_identity import resolve_purchase_material
        from apps.procurement.models import PurchaseGroup, PurchaseOrder, PurchaseOrderLine, PurchaseReturn
        from apps.procurement.pipe_purchase import validate_pipe_purchase_source

        with self.legacy_schema() as old_apps:
            order = self.make_order(old_apps)
            line = self.make_line(old_apps, order)
            saved = self.make_fulfilment(old_apps, order, line)

        self.assert_saved_rows_unchanged(saved)
        old_order = PurchaseOrder.objects.get(pk=order.pk)
        old_line = PurchaseOrderLine.objects.get(pk=line.pk)
        group = old_order.purchase_group
        source = old_line.purchase_group_line
        self.assertEqual(PurchaseGroup.objects.count(), 1)
        self.assertEqual((old_order.batch_number, old_order.batch_type, old_order.batch_request_id), (1, "NORMAL", None))
        self.assertEqual(source.purchase_group_id, group.pk)
        self.assertEqual((group.created_at, group.updated_at), (self.saved_at, self.saved_at))
        self.assertEqual(source.required_quantity, Decimal("100"))
        self.assertEqual(source.source_snapshot["source_quantity_text"], "100")
        self.assertEqual(source.source_snapshot["calculation_snapshot"]["raw_material_id"], str(self.inventory_material.pk))
        self.assertEqual(source.compatibility_issues, [])
        self.assertEqual(old_line.calculation_snapshot, {})
        self.assertEqual(resolve_purchase_material(old_line).pk, self.inventory_material.pk)
        validate_pipe_purchase_source(old_line)

        progress = purchase_group_progress(group)
        self.assertEqual(progress["status"], "PURCHASING")
        self.assertEqual(progress["lines"][0]["purchased_quantity"], Decimal("120"))
        self.assertEqual(progress["lines"][0]["accepted_quantity"], Decimal("80"))
        self.assertEqual(progress["lines"][0]["progress_percent"], Decimal("80"))

        batch, created = create_purchase_batch(
            group_id=group.pk, allowed_task_ids=[self.task.pk], actor_employee=self.employee,
            request=SimpleNamespace(headers={"If-Match": etag_for_instance(group)}, META={}),
            validated_data={"request_id": uuid4(), "batch_type": "SUPPLEMENT", "currency_id": self.cny.pk,
                            "lines": [{"purchase_group_line_id": source.pk, "actual_purchase_quantity": Decimal("30"),
                                       "unit_price": Decimal("2"), "supplier_id": self.supplier.pk}]},
        )
        self.assertTrue(created)
        self.assertEqual((batch.purchase_group_id, batch.batch_number, batch.batch_type), (group.pk, 2, "SUPPLEMENT"))
        self.assertEqual(batch.lines.get().purchase_group_line_id, source.pk)
        self.assertEqual(batch.lines.get().required_quantity, Decimal("100"))
        self.assertEqual(batch.lines.get().calculation_snapshot["raw_material_id"], str(self.inventory_material.pk))
        self.assert_saved_rows_unchanged(saved)
        self.assertEqual(purchase_group_progress(PurchaseGroup.objects.get(pk=group.pk)), progress)

        # 新批次已有独立身份后，回退必须失败，不能静默删除归属或履约。
        with self.assertRaisesRegex(RuntimeError, "不能自动回退"):
            MigrationExecutor(connection).migrate([("procurement", "0024_purchase_groups")])
        self.assertTrue(PurchaseOrder.objects.filter(pk=batch.pk, purchase_group_id=group.pk).exists())
        self.assert_saved_rows_unchanged(saved)

        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label="inventory"))
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        zone_id = MaterialInboundLine.objects.filter(purchase_order_line=old_line).first().zone_id
        received = self.client.post("/api/v1/material-inventory/receivings/", {
            "inbound_date": timezone.localdate().isoformat(), "remark": "迁移后旧单继续补收",
            "items": [{"purchase_order_line_id": str(old_line.pk), "zone_id": str(zone_id),
                       "expected_remaining_quantity": "20", "received_quantity": "20"}],
        }, format="json")
        self.assertEqual(received.status_code, 201, received.data)
        inbound = received.data["data"]
        self.assertEqual(inbound["status"], "PENDING_QUALITY")
        new_inbound_line = MaterialInboundLine.objects.get(inbound_id=inbound["id"])
        self.assertEqual(new_inbound_line.purchase_order_line_id, old_line.pk)
        self.assertEqual(new_inbound_line.raw_material_information_id, self.inventory_material.pk)
        self.assertEqual(purchase_group_progress(PurchaseGroup.objects.get(pk=group.pk)), progress)

        confirmed = self.client.post(f"/api/v1/material-inventory/quality-batches/{inbound['id']}/confirm/", {
            "items": [{"line_id": str(new_inbound_line.pk), "expected_received_quantity": "20",
                       "return_quantity": "5", "quality_remark": "迁后补收检出5件不合格"}],
        }, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        new_inbound_line.refresh_from_db()
        self.assertEqual(new_inbound_line.accepted_quantity, Decimal("15"))
        self.assertEqual(new_inbound_line.return_quantity, Decimal("5"))
        after_quality = purchase_group_progress(PurchaseGroup.objects.get(pk=group.pk))
        self.assertEqual(after_quality["status"], "PURCHASING")
        self.assertEqual(after_quality["lines"][0]["accepted_quantity"], Decimal("95"))
        self.assertEqual(after_quality["lines"][0]["progress_percent"], Decimal("95"))

        returned = PurchaseReturn.objects.get(inbound_id=inbound["id"])
        self.assertEqual(returned.purchase_order_id, old_order.pk)
        self.assertEqual(returned.status, "QUALITY_GENERATED")
        self.assertEqual(returned.lines.get().inbound_line_id, new_inbound_line.pk)
        self.assertEqual(returned.lines.get().quantity, Decimal("5"))
        return_url = f"/api/v1/purchase-returns/{returned.pk}/"
        for action, status in (("confirm", "PROCUREMENT_CONFIRMED"), ("complete", "COMPLETED")):
            detail = self.client.get(return_url)
            self.assertEqual(detail.status_code, 200, detail.data)
            changed = self.client.post(f"{return_url}{action}/", {}, format="json", HTTP_IF_MATCH=detail["ETag"])
            self.assertEqual(changed.status_code, 200, changed.data)
            returned.refresh_from_db()
            self.assertEqual(returned.status, status)
            self.assertEqual(purchase_group_progress(PurchaseGroup.objects.get(pk=group.pk)), after_quality)

        # 新收货只增加原余额；迁移前的入退库、合同和审计行都保持原值。
        self.assertEqual(MaterialStockBalance.objects.get(raw_material=self.inventory_material, zone_id=zone_id).quantity,
                         Decimal("95"))
        self.assert_saved_rows_unchanged([row for row in saved if row[1] != "materialstockbalance"])
        old_line.refresh_from_db()
        self.assertEqual(old_line.calculation_snapshot, {})

    def test_forward_marks_unresolved_history_unknown_without_guessing_identity(self):
        from apps.procurement.group_selectors import purchase_group_progress
        from apps.procurement.models import PurchaseGroup, PurchaseOrderLine

        with self.legacy_schema() as old_apps:
            material_model = old_apps.get_model("products", "RawMaterialInformation")
            material_values = {
                "item_type": "MATERIAL", "category_id": self.inventory_material.category_id,
                "material_name": "只同名不能匹配", "unit_id": self.inventory_material.unit_id,
            }
            material_model.objects.create(material_number="MIGRATION-AMBIGUOUS", source_row_number=2000000201,
                                          **material_values)
            material_model.objects.create(material_number="MIGRATION-AMBIGUOUS", source_row_number=2000000202,
                                          archived_at=self.saved_at, **material_values)
            archived = material_model.objects.create(material_number="MIGRATION-ARCHIVED",
                                                     archived_at=self.saved_at, **material_values)
            cases = [
                ({"source_bom_line_id_snapshot": None}, "SOURCE_ID_MISSING"),
                ({"product_line_id_snapshot": None}, "SOURCE_ID_MISSING"),
                ({"required_quantity": None}, "SUGGESTED_QUANTITY_MISSING"),
                ({"required_quantity": Decimal("0")}, "SUGGESTED_QUANTITY_MISSING"),
                ({"source_unit_text": ""}, "UNIT_MISSING"),
                ({"source_unit_text": "千克"}, "UNIT_MISMATCH"),
                ({"quantity_parse_status": "INVALID"}, "SUGGESTED_QUANTITY_UNRESOLVED"),
                ({"raw_material_snapshot": "只同名不能匹配"}, "MATERIAL_IDENTITY_MISSING"),
                ({"raw_material_snapshot": "MIGRATION-AMBIGUOUS"}, "MATERIAL_IDENTITY_MISSING"),
                ({"raw_material_snapshot": "MIGRATION-ARCHIVED"}, "MATERIAL_IDENTITY_MISSING"),
                ({"calculation_snapshot": {"raw_material_id": str(archived.pk)}}, "MATERIAL_IDENTITY_MISSING"),
                ({"calculation_snapshot": {"raw_material_id": "invalid-id"}}, "MATERIAL_IDENTITY_MISSING"),
                ({"calculation_snapshot": {"raw_material_id": None}}, "MATERIAL_IDENTITY_MISSING"),
                ({"calculation_snapshot": {"raw_material_id": str(self.inventory_material.pk),
                                            "unit_id": str(uuid4())}}, "UNIT_MISMATCH"),
            ]
            order = self.make_order(old_apps)
            rows = [self.make_line(old_apps, order, number, **overrides)
                    for number, (overrides, _) in enumerate(cases, 1)]
            saved = self.saved_rows(order, *rows)

        self.assert_saved_rows_unchanged(saved)
        group = PurchaseGroup.objects.get()
        result = purchase_group_progress(group)
        self.assertEqual(result["status"], "UNKNOWN")
        progress_by_id = {line["id"]: line for line in result["lines"]}
        for old_line, (_, issue) in zip(rows, cases):
            with self.subTest(issue=issue, line=old_line.line_number):
                source = PurchaseOrderLine.objects.get(pk=old_line.pk).purchase_group_line
                self.assertIn(issue, source.compatibility_issues)
                progress = progress_by_id[source.pk]
                self.assertIsNone(progress["progress_percent"])
                self.assertIsNone(progress["accepted_quantity"])
                self.assertIsNone(progress["purchased_quantity"])
                self.assertFalse(progress["is_satisfied"])

    def test_sample_purchase_and_source_binding_are_unchanged(self):
        from apps.procurement.models import PurchaseGroup, PurchaseOrder, PurchaseOrderLine

        with self.legacy_schema() as old_apps:
            sample = old_apps.get_model("samples", "SampleRequest").objects.create(
                request_number="SAMPLE-MIGRATION-ONLY", customer_account_id=self.customer.pk,
                owner_employee_id=self.employee.pk, requested_at=self.saved_at,
            )
            material_request = old_apps.get_model("samples", "SampleMaterialRequest").objects.create(sample_request=sample)
            procurement_request = old_apps.get_model("samples", "SampleMaterialProcurementRequest").objects.create(
                material_request=material_request, lines=[{"key": str(uuid4()), "quantity": "100"}],
            )
            order = self.make_order(old_apps, source_type="SAMPLE", production_task_id=None,
                                    sample_procurement_request_id=procurement_request.pk,
                                    sample_number_snapshot=sample.request_number)
            line = self.make_line(old_apps, order, bom_id=None, bom_line_id=None,
                                  source_bom_line_id_snapshot=None, product_line_id_snapshot=None,
                                  sample_demand_quantity=Decimal("100"), sample_supply_quantity=Decimal("0"))
            binding = old_apps.get_model("samples", "SampleMaterialPurchaseSource").objects.create(
                procurement_request=procurement_request, line_key=procurement_request.lines[0]["key"],
                purchase_order_line=line,
            )
            saved = self.saved_rows(sample, material_request, procurement_request, order, line, binding)

        self.assert_saved_rows_unchanged(saved)
        self.assertFalse(PurchaseGroup.objects.exists())
        order = PurchaseOrder.objects.get(pk=order.pk)
        self.assertIsNone(order.purchase_group_id)
        self.assertIsNone(order.batch_number)
        self.assertIsNone(PurchaseOrderLine.objects.get(pk=line.pk).purchase_group_line_id)

    def test_empty_legacy_order_is_unknown_and_schema_rollback_preserves_original_rows(self):
        from apps.procurement.group_selectors import purchase_group_progress
        from apps.procurement.models import PurchaseOrder

        with self.legacy_schema() as old_apps:
            empty = self.make_order(old_apps)
            archived = self.make_order(old_apps, "CGDD2026092902", archived_at=self.saved_at,
                                       archived_by_employee_id=self.employee.pk, archive_reason="保留归档历史")
            archived_line = self.make_line(old_apps, archived)
            saved = self.saved_rows(empty, archived, archived_line)

        self.assert_saved_rows_unchanged(saved)
        empty_group = PurchaseOrder.objects.get(pk=empty.pk).purchase_group
        self.assertIn("SOURCE_LINES_MISSING", empty_group.compatibility_issues)
        self.assertEqual(purchase_group_progress(empty_group)["status"], "UNKNOWN")
        archived_group = PurchaseOrder.objects.get(pk=archived.pk).purchase_group
        self.assertEqual(archived_group.archived_at, self.saved_at)
        self.assertEqual(archived_group.archive_reason, "保留归档历史")
        with self.legacy_schema() as old_apps:
            self.assert_saved_rows_unchanged(saved, registry=old_apps)
        self.assert_saved_rows_unchanged(saved)

    def test_multiple_saved_products_or_boms_are_unknown_and_cannot_append_batches(self):
        from apps.core.api.exceptions import Conflict
        from apps.procurement.group_selectors import purchase_group_progress
        from apps.procurement.group_services import create_purchase_batch
        from apps.procurement.models import PurchaseOrder

        second_product = self.make_product_line(self.task, line_number=2)
        second_bom, second_line = self.make_bom(second_product, section_type="ACCESSORY", budget_quantity="100")
        newer_bom, newer_line = self.make_bom(self.product_line, version=2, section_type="ACCESSORY", budget_quantity="100")
        with self.legacy_schema() as old_apps:
            mixed_product = self.make_order(old_apps)
            first = self.make_line(old_apps, mixed_product)
            second = self.make_line(old_apps, mixed_product, 2, bom_id=second_bom.pk,
                                    bom_line_id=second_line.pk, source_bom_line_id_snapshot=second_line.pk,
                                    product_line_id_snapshot=second_product.pk)
            mixed_bom = self.make_order(old_apps, "CGDD2026092902")
            third = self.make_line(old_apps, mixed_bom)
            fourth = self.make_line(old_apps, mixed_bom, 2, bom_id=newer_bom.pk,
                                    bom_line_id=newer_line.pk, source_bom_line_id_snapshot=newer_line.pk)
            saved = self.saved_rows(mixed_product, first, second, mixed_bom, third, fourth)

        self.assert_saved_rows_unchanged(saved)
        for order, issue in ((mixed_product, "SOURCE_PRODUCT_AMBIGUOUS"), (mixed_bom, "SOURCE_BOM_AMBIGUOUS")):
            with self.subTest(issue=issue):
                group = PurchaseOrder.objects.get(pk=order.pk).purchase_group
                self.assertIn(issue, group.compatibility_issues)
                self.assertEqual(purchase_group_progress(group)["status"], "UNKNOWN")
                before_count = PurchaseOrder.objects.count()
                with self.assertRaises(Conflict):
                    create_purchase_batch(
                        group_id=group.pk, allowed_task_ids=[self.task.pk], actor_employee=self.employee,
                        request=SimpleNamespace(headers={"If-Match": etag_for_instance(group)}, META={}),
                        validated_data={"request_id": uuid4(), "batch_type": "NORMAL", "currency_id": self.cny.pk,
                                        "lines": [{"purchase_group_line_id": group.lines.first().pk,
                                                   "actual_purchase_quantity": Decimal("1"), "unit_price": Decimal("2")}]},
                    )
                self.assertEqual(PurchaseOrder.objects.count(), before_count)

    def test_schema_rollback_rechecks_new_batches_after_data_migration_was_reversed(self):
        from apps.procurement.group_services import create_purchase_batch
        from apps.procurement.models import PurchaseOrder

        with self.legacy_schema() as old_apps:
            order = self.make_order(old_apps)
            line = self.make_line(old_apps, order)
            saved = self.saved_rows(order, line)
        group = PurchaseOrder.objects.get(pk=order.pk).purchase_group
        final_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        try:
            MigrationExecutor(connection).migrate([("procurement", "0024_purchase_groups")])
            self.assert_saved_rows_unchanged(saved)
            batch, created = create_purchase_batch(
                group_id=group.pk, allowed_task_ids=[self.task.pk], actor_employee=self.employee,
                request=SimpleNamespace(headers={"If-Match": etag_for_instance(group)}, META={}),
                validated_data={"request_id": uuid4(), "batch_type": "NORMAL", "currency_id": self.cny.pk,
                                "lines": [{"purchase_group_line_id": group.lines.get().pk,
                                           "actual_purchase_quantity": Decimal("1"), "unit_price": Decimal("2")}]},
            )
            self.assertTrue(created)
            with self.assertRaisesRegex(RuntimeError, "不能自动回退"):
                MigrationExecutor(connection).migrate([("procurement", "0023_purchase_orders_per_product")])
            self.assertTrue(PurchaseOrder.objects.filter(pk=batch.pk, purchase_group_id=group.pk, batch_number=2).exists())
            self.assert_saved_rows_unchanged(saved)
        finally:
            MigrationExecutor(connection).migrate(final_targets)

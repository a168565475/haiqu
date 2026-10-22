"""入库记录存储约束；使用人工构造的关联行，不替代业务服务/工艺身份验收。"""
import uuid
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.material_issues.models import OrderMaterialRequirement
from ..models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockMovement
from .test_public_stock_services import PublicStockFixture


class InternalReceiptPermissionTests(TestCase):
    def test_receipt_permissions_include_controlled_pending_delete(self):
        codes=set(Permission.objects.filter(content_type__app_label='inventory',
                                            content_type__model='internalsemifinishedreceipt').values_list('codename',flat=True))
        self.assertEqual(codes,{'add_internalsemifinishedreceipt','view_internalsemifinishedreceipt',
                              'confirm_internalsemifinishedreceipt','delete_internalsemifinishedreceipt'})
        self.assertFalse(Permission.objects.filter(content_type__app_label='inventory',content_type__model='internalsemifinishedreceiptline').exists())


class InternalReceiptModelTests(PublicStockFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.input_requirement = OrderMaterialRequirement.objects.create(
            production_task=self.task,raw_material=self.raw_material,unit=self.piece_unit,
            line_type='RAW',section_code='PROFILE',measurement_kind='OTHER',
            required_quantity=1000,source_revision_hash='a'*64,
        )

    def header(self, **changes):
        values=dict(receipt_number='IR-'+uuid.uuid4().hex[:16],request_id=uuid.uuid4(),
                    request_payload_hash='b'*64,schedule_product=self.schedule_product,
                    completed_craft=self.plan_craft,plan_category='METAL',receipt_date=timezone.localdate(),
                    zone=self.semi_zone,actor_employee=self.employee,source_revision_hash='a'*64,
                    source_snapshot={'purpose':'仅数据库约束测试，不是业务入库'},remark='结构约束测试')
        values.update(changes)
        return InternalSemiFinishedReceipt.objects.create(**values)

    def row(self, receipt=None, **changes):
        receipt=receipt or self.header()
        row_id=uuid.uuid4()
        # 已有公共记账服务产生人工测试流水，当前只核对外键及数量约束。
        movement=self.credit(10,identity=self.semi_identity,zone=self.semi_zone,
                             **self.source(source_type='INTERNAL_RECEIPT_SCHEMA_TEST',source_id=receipt.pk,source_line_id=row_id))
        values=dict(id=row_id,receipt=receipt,bom_line=self.bom_line,component_identity=self.bom_line.component_identity,
                    unit=self.piece_unit,input_requirement=self.input_requirement,input_unit_name='支',
                    quantity=10,input_per_output=1,input_quantity=10,required_quantity_snapshot=1000,
                    received_before=0,received_after=10,stock_movement=movement,
                    attribute_snapshot={'purpose':'结构测试'},input_snapshot={'issued':'1000'})
        values.update(changes)
        return InternalSemiFinishedReceiptLine.objects.create(**values)

    def test_request_id_cannot_create_two_receipts(self):
        receipt=self.header()
        with self.assertRaises(IntegrityError),transaction.atomic():
            self.header(request_id=receipt.request_id)

    def test_cutting_and_assembly_cannot_be_internal_semi_stages(self):
        for stage in ['CUTTING','ASSEMBLY','POWDER_COATING','']:
            with self.subTest(stage=stage),self.assertRaises(IntegrityError),transaction.atomic():
                self.header(plan_category=stage)

    def test_before_after_and_original_input_snapshot_are_saved(self):
        row=self.row(received_before=20,received_after=30)
        row.refresh_from_db()
        self.assertEqual((row.received_before,row.received_after,row.input_quantity),(20,30,10))
        self.assertEqual(row.input_snapshot,{'issued':'1000'})
        self.assertEqual(row.stock_movement.source_line_id,row.pk)

    def test_invalid_counts_are_rejected_by_database(self):
        cases=[{'quantity':0,'received_after':0,'input_quantity':0},
               {'quantity':Decimal('1.5'),'received_after':Decimal('1.5'),'input_quantity':Decimal('1.5')},
               {'received_before':-1,'received_after':9},
               {'received_after':11},
               {'required_quantity_snapshot':9},
               {'input_per_output':0,'input_quantity':0},
               {'input_quantity':9},
               {'input_unit_name':'根'},
               {'input_per_output':2,'input_quantity':20}]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(IntegrityError),transaction.atomic():self.row(**changes)

    def test_fabric_meter_use_can_be_decimal(self):
        row=self.row(input_unit_name='米',input_per_output=Decimal('0.325'),input_quantity=Decimal('3.25'))
        self.assertEqual(row.input_quantity,Decimal('3.25'))

    def test_new_sewing_receipt_can_leave_both_meter_fields_unmeasured(self):
        row=self.row(receipt=self.header(plan_category='SEWING'),input_unit_name='米',
                     input_per_output=None,input_quantity=None)
        row.refresh_from_db()
        self.assertIsNone(row.input_per_output)
        self.assertIsNone(row.input_quantity)

    def test_unmeasured_input_is_not_allowed_for_metal_or_partial_null_values(self):
        for changes in (
            {'input_unit_name':'支','input_per_output':None,'input_quantity':None},
            {'input_unit_name':'米','input_per_output':None},
            {'input_unit_name':'米','input_quantity':None},
        ):
            with self.subTest(changes=changes),self.assertRaises(IntegrityError),transaction.atomic():
                self.row(**changes)

    def test_same_component_cannot_appear_twice_on_one_receipt(self):
        row=self.row()
        with self.assertRaises(IntegrityError),transaction.atomic():self.row(receipt=row.receipt)

    def test_one_stock_movement_cannot_back_two_receipt_lines(self):
        row=self.row()
        with self.assertRaises(IntegrityError),transaction.atomic():self.row(stock_movement=row.stock_movement)

    def test_rollback_removes_header_line_and_stock_credit_together(self):
        before=PublicStockMovement.objects.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.row()
                raise RuntimeError('模拟确认事务中断')
        self.assertEqual(PublicStockMovement.objects.count(),before)
        self.assertEqual(InternalSemiFinishedReceipt.objects.count(),0)
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.count(),0)

    def test_receipt_source_and_stock_movement_are_protected(self):
        row=self.row()
        with self.assertRaises(ValidationError):row.delete()
        with self.assertRaises(ValidationError):row.receipt.delete()
        with self.assertRaises(ProtectedError):row.stock_movement.delete()
        with self.assertRaises(ProtectedError):row.bom_line.delete()

    def test_queryset_and_related_manager_cannot_delete_receipt_history(self):
        row=self.row()
        with self.assertRaises(ValidationError):InternalSemiFinishedReceiptLine.objects.filter(pk=row.pk).delete()
        with self.assertRaises(ValidationError):row.receipt.lines.all().delete()
        with self.assertRaises(ValidationError):InternalSemiFinishedReceipt.objects.filter(pk=row.receipt_id).delete()
        self.assertEqual(InternalSemiFinishedReceiptLine.objects.count(),1)
        self.assertTrue(PublicStockMovement.objects.filter(pk=row.stock_movement_id).exists())

    def test_empty_header_cannot_be_batch_deleted(self):
        receipt=self.header()
        with self.assertRaises(ValidationError):InternalSemiFinishedReceipt.objects.filter(pk=receipt.pk).delete()

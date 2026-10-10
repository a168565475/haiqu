import copy
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.inventory import material_flow_reset as reset
from apps.procurement.models import PurchaseOrder, PurchaseOrderLine
from apps.procurement.tests import test_pipe_purchase_flow as pipe_fixture


class MaterialFlowResetTests(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.f = pipe_fixture.PipePurchaseFlowTests(methodName='test_pending_receipt_does_not_credit_and_quality_creates_root_meter_balance')
        with transaction.atomic():
            self.f.setUp()
        receipt = self.f.receive(4)
        self.assertEqual(receipt.status_code, 201, receipt.data)
        quality = self.f.quality(receipt, returned=1)
        self.assertEqual(quality.status_code, 200, quality.data)

    def run_reset(self, manifest=None):
        manifest = manifest or reset.preview()
        return reset.execute(manifest, manifest['sha256'], connection.settings_dict['NAME'], operator='S8 隔离测试')

    def test_preview_is_stable_and_read_only(self):
        before = reset.table_snapshot()
        self.assertEqual(reset.preview(), reset.preview())
        self.assertEqual(before, reset.table_snapshot())

    def test_reset_removes_batches_returns_stock_but_preserves_other_tables(self):
        before = reset.preview()
        self.assertFalse(before['blockers'])
        result = self.run_reset(before)
        self.assertTrue(result['ok'])
        for label in reset.DELETE_LABELS:
            self.assertEqual(apps.get_model(label).objects.count(), 0, label)
        self.f.purchase_line.refresh_from_db()
        self.assertIsNone(self.f.purchase_line.unit_price)
        self.assertIsNone(self.f.purchase_line.amount)
        self.assertIsNone(self.f.purchase_line.actual_purchase_quantity)
        self.assertEqual(self.f.purchase_line.suggested_purchase_meters, Decimal('12.20'))
        self.assertEqual(set(PurchaseOrder.objects.values_list('status', flat=True)), {'DRAFT'})
        after = reset.table_snapshot()
        for table in before['protected_tables']:
            if table != 'audit_log':
                self.assertEqual(before['tables'][table], after[table], table)
        self.assertEqual(after['audit_log']['count'], before['tables']['audit_log']['count']+1)

    def test_bad_digest_and_wrong_database_do_not_write(self):
        manifest = reset.preview()
        before = reset.table_snapshot()
        with self.assertRaises(CommandError):
            reset.execute(manifest, '0'*64, connection.settings_dict['NAME'], operator='S8 隔离测试')
        with self.assertRaises(CommandError):
            reset.execute(manifest, manifest['sha256'], 'haiqu_erp', operator='S8 隔离测试')
        self.assertEqual(before, reset.table_snapshot())

    def test_source_content_drift_even_without_count_change_stops(self):
        manifest = reset.preview()
        PurchaseOrder.objects.filter(pk=self.f.purchase_line.purchase_order_id).update(completion_remark='新业务')
        before = reset.table_snapshot()
        with self.assertRaisesMessage(CommandError, '漂移'):
            self.run_reset(manifest)
        self.assertEqual(before, reset.table_snapshot())

    def test_schema_drift_stops(self):
        manifest = reset.preview()
        with connection.cursor() as cursor:
            cursor.execute('CREATE INDEX s8_test_drift_index ON procurement_purchase_order (completion_remark)')
        try:
            with self.assertRaisesMessage(CommandError, '漂移'):
                self.run_reset(manifest)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX s8_test_drift_index')

    def test_retention_failure_rolls_back_all_deletions_and_updates(self):
        manifest = reset.preview()
        original = reset.table_snapshot
        calls = 0
        def damaged_snapshot():
            nonlocal calls
            result = original()
            calls += 1
            if calls == 2:
                table = next(t for t in manifest['protected_tables'] if t != 'audit_log')
                result[table]['count'] += 1
            return result
        with patch.object(reset, 'table_snapshot', side_effect=damaged_snapshot):
            with self.assertRaisesMessage(CommandError, '保留对象'):
                self.run_reset(manifest)
        self.assertEqual(manifest['tables'], reset.table_snapshot())

    def test_replay_old_and_new_manifest_cannot_reset_new_business(self):
        manifest = reset.preview()
        self.run_reset(manifest)
        PurchaseOrder.objects.update(completion_remark='清理后的新业务')
        with self.assertRaises(CommandError):
            self.run_reset(manifest)
        with self.assertRaisesMessage(CommandError, '已执行过'):
            self.run_reset()
        self.assertEqual(PurchaseOrder.objects.first().completion_remark, '清理后的新业务')

    def test_non_pipe_price_quantity_and_amount_are_preserved(self):
        line = PurchaseOrderLine.objects.get(pk=self.f.purchase_line.pk)
        line.pk = uuid.uuid4()
        line.line_number += 100
        line.source_bom_line_id_snapshot = None
        line.section_type_snapshot = 'HARDWARE'
        line.raw_bar_length_m = line.suggested_bar_count = line.suggested_purchase_meters = None
        line.actual_bar_count = line.actual_purchase_meters = None
        line.calculation_snapshot = {}
        line.save(force_insert=True)
        expected = (line.unit_price, line.actual_purchase_quantity, line.amount)
        self.run_reset()
        line.refresh_from_db()
        self.assertEqual((line.unit_price, line.actual_purchase_quantity, line.amount), expected)

    def test_missing_pipe_parameters_are_not_fabricated(self):
        from apps.reference_data.models import Currency
        self.f.order.currency=Currency.objects.get(code='CNY')
        self.f.order.currency_code_snapshot='CNY'
        self.f.order.save()
        bom_line = self.f.bom_line
        for field in ('cutting_length_mm','pieces_per_product','pieces_per_bar','raw_bar_length_m','suggested_bar_count','suggested_purchase_meters'):
            setattr(bom_line,field,None)
        bom_line.length_value = ''
        bom_line.save()
        manifest = reset.preview()
        self.assertTrue(manifest['warnings'])
        self.run_reset(manifest)
        self.f.purchase_line.refresh_from_db()
        self.assertIsNone(self.f.purchase_line.required_quantity)
        self.assertIsNone(self.f.purchase_line.raw_bar_length_m)
        from apps.boms.material_flow_calculations import pipe_plan
        for field,value in pipe_plan(cutting_length_mm=500,pieces_per_product=2,pieces_per_bar=6,order_quantity=10).items():
            if hasattr(bom_line,field):setattr(bom_line,field,value)
        bom_line.save()
        order = self.f.purchase_line.purchase_order
        from apps.core.api.concurrency import etag_for_instance
        from django.utils import timezone
        order.refresh_from_db()
        url=f'/api/v1/purchase-orders/{order.pk}/'
        response=self.f.client.patch(url,{'lines':[{'id':str(self.f.purchase_line.pk),
            'supplier_id':str(self.f.supplier.pk),'delivery_date':timezone.localdate().isoformat(),
            'actual_bar_count':4,'unit_price':'3'}]},format='json',HTTP_IF_MATCH=etag_for_instance(order))
        self.assertEqual(response.status_code,200,response.data)
        confirmed=self.f.client.post(url+'confirm/',{},format='json',HTTP_IF_MATCH=response['ETag'])
        self.assertEqual(confirmed.status_code,200,confirmed.data)
        self.f.purchase_line.refresh_from_db()
        self.assertEqual(self.f.purchase_line.amount,Decimal('36.60'))

    def test_command_preview_and_missing_execution_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory)/'preview.json')
            call_command('reset_material_flow', output=output)
            self.assertTrue(Path(output).exists())
            with self.assertRaises(CommandError):
                call_command('reset_material_flow', output=output)
            with self.assertRaises(CommandError):
                call_command('reset_material_flow', output=str(Path(directory)/'execute.json'), execute=True)

    def test_exact_decimal_changes_are_detected(self):
        line = self.f.purchase_line
        PurchaseOrderLine.objects.filter(pk=line.pk).update(unit_price=Decimal('9999999999999.0001'))
        first = reset.table_snapshot()['procurement_purchase_order_line']['sha256']
        PurchaseOrderLine.objects.filter(pk=line.pk).update(unit_price=Decimal('9999999999999.0002'))
        self.assertNotEqual(first, reset.table_snapshot()['procurement_purchase_order_line']['sha256'])

    def test_old_etag_is_rejected_after_reset(self):
        from types import SimpleNamespace
        from apps.core.api.concurrency import etag_for_instance, require_matching_etag, PreconditionFailed
        order = self.f.purchase_line.purchase_order
        old = etag_for_instance(order)
        self.run_reset()
        order.refresh_from_db()
        with self.assertRaises(PreconditionFailed):
            require_matching_etag(SimpleNamespace(headers={'If-Match':old}), order)

    def test_reset_legacy_pipe_refreshes_only_after_bom_is_ready(self):
        from apps.procurement.reset_sources import refresh_reset_purchase_source
        from apps.procurement.pipe_purchase import validate_pipe_purchase_source
        bom = self.f.bom_line
        bom.length_value, bom.unit_consumption, bom.raw_values = '500','2',{**bom.raw_values,'tube_cut_piece_count':'6'}
        from apps.boms.material_flow_calculations import pipe_plan
        fields_to_restore = pipe_plan(cutting_length_mm=500,pieces_per_product=2,pieces_per_bar=6,order_quantity=10)
        for field in ('cutting_length_mm','pieces_per_product','pieces_per_bar','raw_bar_length_m','suggested_bar_count','suggested_purchase_meters'):
            setattr(bom,field,None)
        bom.save()
        self.run_reset()
        line = PurchaseOrderLine.objects.select_related('purchase_order','bom_line__section__bom').get(pk=self.f.purchase_line.pk)
        self.assertTrue(line.calculation_snapshot['requires_source_confirmation'])
        from rest_framework.exceptions import APIException
        with self.assertRaises(APIException):
            refresh_reset_purchase_source(line)
        for field in ('cutting_length_mm','pieces_per_product','pieces_per_bar','raw_bar_length_m','suggested_bar_count','suggested_purchase_meters'):
            setattr(bom,field,fields_to_restore[field])
        bom.save()
        line = PurchaseOrderLine.objects.select_related('purchase_order','bom_line__section__bom').get(pk=line.pk)
        fields = refresh_reset_purchase_source(line)
        self.assertIn('required_quantity', fields)
        self.assertNotIn('requires_source_confirmation', line.calculation_snapshot)
        validate_pipe_purchase_source(line)

    def test_old_purchase_description_cannot_accept_a_changed_material(self):
        line=self.f.bom_line
        line.part_name='另一种新材料'
        line.save()
        manifest=reset.preview()
        self.assertTrue(any('人工核对' in warning['reason'] for warning in manifest['warnings']))
        self.run_reset(manifest)
        from apps.procurement.reset_sources import refresh_reset_purchase_source
        from apps.core.api.exceptions import Conflict
        self.f.purchase_line.refresh_from_db()
        with self.assertRaises(Conflict):
            refresh_reset_purchase_source(self.f.purchase_line)

    def test_existing_finished_goods_and_sample_stock_and_outbound_are_preserved(self):
        from apps.inventory.tests import test_inventory_api as goods_fixture
        from apps.samples.tests import test_sample_inventory_receipt_api as sample_fixture
        goods=goods_fixture.FinishedGoodsInventoryApiTests(methodName='create_receipt')
        sample=sample_fixture.SampleInventoryReceiptApiTests(methodName='test_sample_outbound_synchronizes_linked_finished_goods_quantity')
        with transaction.atomic():
            goods.setUp()
            sample.setUp()
        goods.create_receipt()
        sample.test_sample_outbound_synchronizes_linked_finished_goods_quantity()
        before=reset.preview()
        self.assertGreater(before['tables']['inventory_finished_goods_receipt']['count'],0)
        self.run_reset(before)
        after=reset.table_snapshot()
        for table in before['protected_tables']:
            if table!='audit_log':self.assertEqual(before['tables'][table],after[table],table)

    def test_non_pipe_blocked_source_can_be_repaired_but_later_change_is_rejected(self):
        bom_line=self.f.bom_line
        bom_line.section.section_type='ACCESSORY'; bom_line.section.save()
        bom_line.unit='根'; bom_line.budget_quantity='12'; bom_line.save()
        self.f.bom.status='PENDING_CONFIRMATION'; self.f.bom.save()
        line=self.f.purchase_line
        line.section_type_snapshot='ACCESSORY'; line.source_unit_text='根'
        line.raw_bar_length_m=line.suggested_bar_count=line.suggested_purchase_meters=None
        line.actual_bar_count=line.actual_purchase_meters=None
        line.calculation_snapshot={}; line.save()
        self.run_reset()
        from apps.procurement.reset_sources import refresh_reset_purchase_source,validate_reset_source
        from apps.core.api.exceptions import Conflict
        self.f.bom.status='VERIFIED'; self.f.bom.save()
        line=PurchaseOrderLine.objects.select_related('purchase_order','bom_line__section__bom').get(pk=line.pk)
        refresh_reset_purchase_source(line)
        self.assertEqual(Decimal(line.required_quantity),12)
        line.save()
        validate_reset_source(line)
        bom_line.budget_quantity='15'; bom_line.save()
        line=PurchaseOrderLine.objects.select_related('purchase_order','bom_line__section__bom').get(pk=line.pk)
        with self.assertRaises(Conflict):validate_reset_source(line)


class MaterialResetExecutionChainTests(TransactionTestCase):
    serialized_rollback = True

    def test_outsourcing_completed_reconciliation_and_issued_materials_are_all_removed(self):
        from apps.material_issues.tests import test_material_flow as issue_fixture
        from apps.outsourcing.tests import test_material_flow as outsourcing_fixture
        f = issue_fixture.MaterialIssueFlowTests(methodName='test_read_and_preview_do_not_create_or_change_stock')
        with transaction.atomic():
            f.setUp()
        key = f.pending()
        f.action(key, 'confirm-issue', {'request_id':str(uuid.uuid4())})
        # 复用同一真实业务夹具的完整外发、退原料、合格/不良回货及结清动作。
        for name in ['post','create','dispatch','raw_return','reconcile','return_goods']:
            setattr(f, name, getattr(outsourcing_fixture.MaterialFlowFixture, name).__get__(f))
        order_id = f.create(amount='396')
        _, source = f.dispatch(order_id,amount='396')
        f.raw_return(order_id, source, 2)
        f.reconcile(order_id, source, 'RAW_INPUT',64)
        f.return_goods(order_id,source,380,0)
        f.reconcile(order_id,source,'OUTPUT_SCRAP',4)
        f.post(order_id,'complete',{'request_id':str(uuid.uuid4())})
        manifest = reset.preview()
        reset.execute(manifest,manifest['sha256'],connection.settings_dict['NAME'],operator='S8 链路测试')
        for label in reset.DELETE_LABELS:
            self.assertEqual(apps.get_model(label).objects.count(),0,label)

    def test_finished_sample_is_preserved_and_new_arrival_writes_once(self):
        from apps.procurement.tests import test_sample_pipe_flow as sample_fixture
        from apps.samples.models import SampleMaterialArrival
        from apps.samples.material_arrival_services import receive_material_arrival
        from types import SimpleNamespace
        f = sample_fixture.SamplePipeFlowTests(methodName='test_source_uses_shortage_pieces_and_server_computes_amount')
        with transaction.atomic():
            f.setUp()
        f.purchasing()
        received = f.receive(4)
        self.assertEqual(received.status_code,201,received.data)
        result = f.quality(received)
        self.assertEqual(result.status_code,200,result.data)
        f.sample.refresh_from_db()
        # 已制成样品的阶段由原业务维护，本用例只设置隔离状态验证清理不回退。
        type(f.sample).objects.filter(pk=f.sample.pk).update(status='FINISHED')
        manifest = reset.preview()
        reset.execute(manifest,manifest['sha256'],connection.settings_dict['NAME'],operator='S8 打样测试')
        f.sample.refresh_from_db()
        self.assertEqual(f.sample.status,'FINISHED')
        f.order.refresh_from_db()
        self.assertEqual(f.order.status,'DRAFT')
        self.assertFalse(SampleMaterialArrival.objects.exists())
        # 重新定价和确认后形成新到货，检查不会再次推进或回退完成状态。
        line = f.purchase_line
        line.refresh_from_db()
        line.actual_bar_count, line.actual_purchase_meters, line.actual_purchase_quantity = 4,Decimal('12.20'),Decimal('12.20')
        line.unit_price, line.amount = Decimal('2'),Decimal('24.40')
        line.save()
        f.order.status='PURCHASING'; f.order.save()
        received = f.receive(4)
        self.assertEqual(received.status_code,201,received.data)
        result = f.quality(received)
        self.assertEqual(result.status_code,200,result.data)
        arrival = SampleMaterialArrival.objects.get()
        receive_material_arrival(procurement_request_id=f.procurement.pk,line_key=f.key,
            inbound_line_id=arrival.inbound_line_id,request=SimpleNamespace(user=f.user,employee=f.employee))
        self.assertEqual(SampleMaterialArrival.objects.count(),1)
        f.sample.refresh_from_db(); self.assertEqual(f.sample.status,'FINISHED')

from django.utils import timezone
from rest_framework.test import APITestCase

from ..inventory_selectors import eligible_sample_items_for_inventory
from ..models import SampleMaterialRequest, SampleWorkflowRecord, SampleWorkflowStage
from . import test_sample_inventory_receipt_api as receipt_tests


class InventoryAfterRequirementEditTests(APITestCase):
    setUp = receipt_tests.SampleInventoryReceiptApiTests.setUp
    payload = receipt_tests.SampleInventoryReceiptApiTests.payload

    def prepare_application(self):
        self.sample_request.application_payload_hash = 'editable-application'
        self.sample_request.save(update_fields=['application_payload_hash'])
        SampleMaterialRequest.objects.create(sample_request=self.sample_request, no_materials=True)
        from apps.files.models import BusinessFile
        image = BusinessFile.objects.create(original_name='parameter.png', storage_key='test/parameter.png',
                                            content_type='image/png', size_bytes=8, scan_status='CLEAN')
        for stage in [SampleWorkflowStage.MATERIALS_READY, SampleWorkflowStage.METALWORK_PARAMETERS, SampleWorkflowStage.CUTTING_PARAMETERS]:
            SampleWorkflowRecord.objects.create(sample_request=self.sample_request, stage=stage,
                                                operated_by_employee=self.employee, operated_at=timezone.now(),
                                                business_file=image)
        self.sample_item.sample_quantity = 10
        self.sample_item.cutting_reported_quantity = 4
        self.sample_item.save(update_fields=['sample_quantity', 'cutting_reported_quantity'])

    def test_editing_quantity_does_not_increase_unreported_inventory(self):
        self.prepare_application()
        item = eligible_sample_items_for_inventory().get(pk=self.sample_item.pk)
        self.assertEqual(item.remaining_quantity, 2)  # 已报工4，累计入库2；需求10不增加额度。
        rejected = self.client.post('/api/v1/sample-inventory/receipts/', self.payload(received_quantity=3), format='json')
        self.assertEqual(rejected.status_code, 409, rejected.data)
        accepted = self.client.post('/api/v1/sample-inventory/receipts/', self.payload(received_quantity=2), format='json')
        self.assertEqual(accepted.status_code, 201, accepted.data)
        self.assertFalse(eligible_sample_items_for_inventory().filter(pk=self.sample_item.pk).exists())

    def test_legacy_inventory_quantity_contract_is_preserved(self):
        self.sample_item.sample_quantity = 10
        self.sample_item.save(update_fields=['sample_quantity'])
        self.assertEqual(eligible_sample_items_for_inventory().get(pk=self.sample_item.pk).remaining_quantity, 8)

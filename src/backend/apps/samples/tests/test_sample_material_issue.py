import uuid
from unittest.mock import patch

from rest_framework.test import APITestCase

from ..models import SampleMaterialIssue, SampleMaterialIssueStatus, SampleRequest
from .test_material_api import SampleMaterialApiTests


class SampleMaterialIssueApiTests(SampleMaterialApiTests):
    def test_full_supply_requires_issue_then_confirms_actual_quantity(self):
        state = self.to_warehouse()
        ready = self.put('warehouse-review', self.supplies(state, ('12', '6', '4')), True, state['ETag'])
        self.assertEqual(ready.status_code, 200, ready.data)
        self.assertEqual(ready.data['data']['status'], 'MATERIAL_ISSUE_PENDING')

        issue_state = self.client.get(self.root + 'material-issue/')
        self.assertEqual(issue_state.status_code, 200, issue_state.data)
        self.assertEqual(issue_state.data['data']['status'], 'NOT_STARTED')
        self.assertTrue(issue_state.data['data']['canInitiate'])
        initiated = self.client.post(
            self.root + 'material-issue/initiate/',
            {'client_request_id': str(uuid.uuid4()), 'note': '整单领料'},
            format='json', HTTP_IF_MATCH=issue_state['ETag'],
        )
        self.assertEqual(initiated.status_code, 200, initiated.data)
        self.assertEqual(initiated.data['data']['status'], SampleMaterialIssueStatus.PENDING_CONFIRMATION)
        self.assertEqual(SampleRequest.objects.get(pk=self.root.split('/')[-2]).status, 'MATERIAL_ISSUE_REVIEW')

        lines = initiated.data['data']['lines']
        with patch('apps.samples.sample_issue_services.debit_material_stock') as debit:
            confirmed = self.client.post(
                self.root + 'material-issue/confirm/',
                {
                    'request_id': str(uuid.uuid4()),
                    'lines': [{'line_id': line['id'], 'issued_quantity': line['availableQuantity']} for line in lines],
                },
                format='json', HTTP_IF_MATCH=initiated['ETag'],
            )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data['data']['status'], SampleMaterialIssueStatus.ISSUED)
        self.assertEqual(SampleMaterialIssue.objects.get().status, SampleMaterialIssueStatus.ISSUED)
        self.assertEqual(SampleRequest.objects.get(pk=self.root.split('/')[-2]).status, 'METALWORK_PENDING')
        self.assertEqual(debit.call_count, len(lines))

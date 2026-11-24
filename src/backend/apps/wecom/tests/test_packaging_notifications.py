from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boms.models import BomLine
from apps.boms.notification_events import EVENT_CODE, PACKAGING_EVENT_CODE
from apps.access_control.models import MaterialSectionGrant
from apps.inventory.tests import test_packaging_receiving_flow as receiving_fixture
from apps.organizations.models import EmployeeRoleAssignment
from apps.procurement.models import PurchaseOrderLine
from apps.procurement.purchase_scope import PACKAGING_PERMISSION
from apps.procurement.tracking_runner import recompute_tracking
from apps.procurement.tracking_rules import BEIJING
from apps.procurement.tracking_selectors import coverage_rows
from apps.procurement.tracking_models import PurchaseTrackingContent
from apps.wecom.management.commands.configure_confirmed_notifications import notification_plan
from apps.wecom.models import NotificationEvent
from apps.wecom.notification_selectors import recipient_payload

from .test_notifications import SETTINGS, create_rule, employee, grant_role
from .test_task_bom_notifications import aggregation_fixture, verify


@override_settings(**SETTINGS, CONFIRMED_ROLE_POLICY_ENABLED=True, PURCHASE_TRACKING_ENABLED=False,
                   PURCHASE_TRACKING_WECOM_ENABLED=False)
class PackagingNotificationsTests(TestCase):
    def test_packaging_only_bom_reminds_current_merchandiser(self):
        f = aggregation_fixture(two=False, saved_rule=False)
        line = BomLine.objects.get(section__bom=f.bom)
        line.section.title = '包材类'
        line.section.save(update_fields=['title'])
        line.category = '包材'
        line.raw_values = {**line.raw_values, 'units_per_box': '1'}
        line.save(update_fields=['category', 'raw_values'])
        actor = employee('PACKAGING_FOLLOWER')
        role = grant_role(actor, 'MERCHANDISER', PACKAGING_PERMISSION, 'FOLLOWED')
        other = employee('UNRELATED_FOLLOWER')
        EmployeeRoleAssignment.objects.create(employee=other, role_profile=role, effective_from=timezone.now())
        f.task.followers.add(actor)
        purchasing = employee('STANDARD_BUYER')
        grant_role(purchasing, 'PURCHASING', 'procurement.add_purchaseorder')
        create_rule(EVENT_CODE, f.employee, ['PURCHASING'], recipient_scope='ROLE_POLICY')
        create_rule(PACKAGING_EVENT_CODE, f.employee, ['MERCHANDISER'], recipient_scope='ROLE_POLICY')

        verify(f, f.bom)
        standard = NotificationEvent.objects.get(event_code=EVENT_CODE)
        self.assertFalse(standard.recipients.exists())
        notice = NotificationEvent.objects.get(event_code=PACKAGING_EVENT_CODE).recipients.get()
        self.assertEqual(notice.employee_id, actor.pk)
        payload = recipient_payload(notice, actor.user)
        self.assertIn(f.task.task_number, payload['body'])
        self.assertIn('包材采购', payload['body'])
        self.assertEqual(payload['target']['route_name'], 'packaging-purchase-create')
        self.assertEqual(payload['target']['object_id'], str(f.task.pk))
        f.task.followers.remove(actor)
        self.assertFalse(recipient_payload(notice, actor.user)['target_accessible'])
        plan = notification_plan([PACKAGING_EVENT_CODE])
        self.assertEqual([row['event_code'] for row in plan['rules']], [PACKAGING_EVENT_CODE])
        self.assertFalse(plan['will_send'])

    def test_tracking_scanner_and_page_respect_two_packaging_task_owners(self):
        fixture = receiving_fixture.PackagingReceivingFlowTests('test_confirmed_packages_receive_quality_and_return_by_original_task')
        fixture.setUp()
        buyer = employee('TRACKING_STANDARD_BUYER')
        grant_role(buyer, 'PURCHASING', 'procurement.view_purchaseorder')
        follower = employee('TRACKING_PACKAGE_A')
        role = grant_role(follower, 'MERCHANDISER', PACKAGING_PERMISSION, 'FOLLOWED')
        other = employee('TRACKING_PACKAGE_B')
        EmployeeRoleAssignment.objects.create(employee=other, role_profile=role, effective_from=timezone.now())
        pmc = employee('TRACKING_PMC')
        grant_role(pmc, 'PMC', 'procurement.view_purchaseorder')
        for order, owner in ((fixture.first, follower), (fixture.second, other)):
            order.production_task.followers.add(owner)
        for code in ('PURCHASE_TRACKING_RISK', 'PURCHASE_TRACKING_DIGEST'):
            create_rule(code, fixture.employee, ['PURCHASING', 'MERCHANDISER', 'PMC'], recipient_scope='ROLE_POLICY')
        PurchaseOrderLine.objects.update(delivery_date=timezone.localdate() - timedelta(days=1))
        next_day = timezone.now().astimezone(BEIJING) + timedelta(days=1)
        morning = next_day.replace(hour=8, minute=30, second=0, microsecond=0)
        with override_settings(PURCHASE_TRACKING_ENABLED=True, PURCHASE_TRACKING_PACKAGING_AUTO_ENABLED=True):
            recompute_tracking(now=morning)
            recompute_tracking(now=morning + timedelta(hours=1))
        instant = NotificationEvent.objects.filter(event_code='PURCHASE_TRACKING_RISK', recipients__employee=follower)
        self.assertTrue(instant.exists())
        self.assertTrue(all(event.target['query']['purchase_scope'] == 'PACKAGING' for event in instant))
        buyer_messages = PurchaseTrackingContent.objects.filter(delivery__recipient__employee=buyer)
        self.assertTrue(buyer_messages.exists())
        self.assertTrue(all(item['snapshot']['purchase_scope'] == 'STANDARD'
                            for message in buyer_messages for item in message.items))
        digest = NotificationEvent.objects.get(event_code='PURCHASE_TRACKING_DIGEST', recipients__employee=follower)
        recipient = digest.recipients.get()
        payload = recipient_payload(recipient, follower.user)
        self.assertIn(fixture.first.production_task_number_snapshot, payload['body'])
        self.assertNotIn(fixture.second.production_task_number_snapshot, payload['body'])
        self.assertEqual(payload['target']['query']['purchase_scope'], 'PACKAGING')
        self.assertEqual(set(digest.recipients.get().deliveries.values_list('channel', 'status')),
                         {('IN_APP', 'ACCEPTED'), ('WECOM', 'SKIPPED')})
        pmc_digest = NotificationEvent.objects.get(event_code='PURCHASE_TRACKING_DIGEST', recipients__employee=pmc).recipients.get()
        pmc_payload = recipient_payload(pmc_digest, pmc.user)
        self.assertIn(fixture.first.production_task_number_snapshot, pmc_payload['body'])
        self.assertIn(fixture.second.production_task_number_snapshot, pmc_payload['body'])

        client = APIClient()
        url = '/api/v1/purchase-tracking/arrivals/'
        client.force_authenticate(buyer.user)
        self.assertEqual(client.get(url).data['data'], [])
        self.assertEqual(client.get(url, {'purchase_scope': 'PACKAGING'}).status_code, 403)
        client.force_authenticate(follower.user)
        result = client.get(url, payload['target']['query'] | {'tab': 'arrival'})
        self.assertEqual(result.status_code, 400)  # tab is a page-only parameter
        result = client.get(url, {'purchase_scope': 'PACKAGING'})
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual({row['production_task_id'] for row in result.data['data']}, {str(fixture.first.production_task_id)})
        self.assertEqual(client.get(url, {'purchase_scope': 'STANDARD'}).status_code, 403)
        tracked_task = [fixture.first.production_task_id]
        packaging = coverage_rows(task_ids=tracked_task, purchase_scope='PACKAGING')
        ordinary = coverage_rows(task_ids=tracked_task)
        self.assertTrue(packaging)
        self.assertTrue(ordinary)
        self.assertTrue(all(row['material_category_key'] == 'PACKAGING' for row in packaging))
        self.assertTrue(all(row['material_category_key'] != 'PACKAGING' for row in ordinary))
        fixture.first.production_task.followers.remove(follower)
        self.assertFalse(recipient_payload(recipient, follower.user)['target_accessible'])

    def test_package_receipt_and_inspection_notify_quality_pmc_and_follower(self):
        fixture = receiving_fixture.PackagingReceivingFlowTests('test_confirmed_packages_receive_quality_and_return_by_original_task')
        fixture.setUp()
        fixture.scoped_actor()
        grant = fixture.grant('inventory.receive_material', 'MATERIAL')
        MaterialSectionGrant.objects.create(grant=grant, sections=['PACKAGING'])
        quality = employee('PACKAGING_QUALITY')
        grant_role(quality, 'QUALITY', 'inventory.quality_confirm_material')
        buyer = employee('PACKAGING_RECEIPT_BUYER')
        grant_role(buyer, 'PURCHASING', 'procurement.view_purchaseorder')
        pmc = employee('PACKAGING_RECEIPT_PMC')
        grant_role(pmc, 'PMC', 'procurement.view_purchaseorder')
        follower = employee('PACKAGING_RECEIPT_FOLLOWER')
        grant_role(follower, 'MERCHANDISER', PACKAGING_PERMISSION, 'FOLLOWED')
        fixture.first.production_task.followers.add(follower)
        create_rule('MATERIAL_RECEIPT_RECORDED', fixture.employee, ['QUALITY', 'PMC', 'PURCHASING', 'MERCHANDISER'],
                    recipient_scope='ROLE_POLICY')
        create_rule('MATERIAL_INSPECTION_CONFIRMED', fixture.employee, ['PMC', 'PURCHASING', 'MERCHANDISER'],
                    recipient_scope='ROLE_POLICY')
        line = fixture.first.lines.get()
        received = fixture.client.post(receiving_fixture.INVENTORY + 'receivings/', {
            'material_section': 'D', 'items': [{'purchase_order_line_id': str(line.pk), 'zone_id': str(fixture.zone.pk),
                                              'received_quantity': '240', 'expected_remaining_quantity': '500'}],
        }, format='json')
        self.assertEqual(received.status_code, 201, received.data)
        receipt = NotificationEvent.objects.get(event_code='MATERIAL_RECEIPT_RECORDED')
        self.assertEqual(set(receipt.recipients.values_list('employee_id', flat=True)), {quality.pk, pmc.pk, follower.pk})
        todo = receipt.recipients.get(employee=quality)
        self.assertEqual(recipient_payload(todo, quality.user)['target']['route_name'], 'material-quality-confirmation')
        fixture.client.force_authenticate(quality.user)
        confirmed = fixture.confirm_quality(received, return_quantity='40')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertFalse(recipient_payload(todo, quality.user)['target_accessible'])
        result = NotificationEvent.objects.get(event_code='MATERIAL_INSPECTION_CONFIRMED')
        self.assertEqual(set(result.recipients.values_list('employee_id', flat=True)), {pmc.pk, follower.pk})
        payload = recipient_payload(result.recipients.get(employee=pmc), pmc.user)
        self.assertEqual(payload['target']['params']['id'], str(fixture.first.pk))
        self.assertIn('200', payload['body'])
        self.assertIn('40', payload['body'])
        fixture.client.force_authenticate(pmc.user)
        self.assertEqual(fixture.client.get(f'/api/v1/purchase-orders/{fixture.first.pk}/details/').status_code, 200)

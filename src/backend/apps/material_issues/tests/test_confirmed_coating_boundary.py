"""喷塑岗位只能接续已建立的原来源关系；真实API和隔离库回归。"""
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.access_control.models import RoleActionGrant, RoleGrantResource
from apps.material_issues.models import MetalProcessingOriginalHandoff, MetalProcessingSource
from apps.wecom.tests.test_notifications import SETTINGS, employee, grant_role
from .test_metal_processing_p4 import MetalProcessingP4Fixture


@override_settings(**SETTINGS, CONFIRMED_ROLE_POLICY_ENABLED=True, TUBE_OUTSOURCING_ENABLED=False)
class ConfirmedCoatingBoundaryTests(MetalProcessingP4Fixture, APITestCase):
    def coating_user(self):
        member = employee('CONFIRMED_COATING')
        role = grant_role(member, 'COATING_MATERIALS', 'material_issues.create_metalprocessingoriginalhandoff', 'CRAFT')
        for code in ('material_issues.view_metalprocessingsource', 'outsourcing.view_outsourcingorder'):
            app, codename = code.split('.')
            permission = Permission.objects.get(content_type__app_label=app, codename=codename)
            RoleActionGrant.objects.create(role=role, permission=permission, scope='CRAFT')
        for grant in RoleActionGrant.objects.filter(role=role):
            RoleGrantResource.objects.create(grant=grant, craft=self.f.spray)
        role.auth_group.permissions.set(RoleActionGrant.objects.filter(role=role).values_list('permission_id', flat=True))
        self.client.force_authenticate(member.user)
        return member

    def handoff_payload(self, pieces=2):
        return {'request_id': str(uuid4()), 'original_order_id': self.original_order,
                'factory_id': str(self.f.factory.pk), 'handoff_pieces': pieces,
                'handoff_date': str(timezone.localdate())}

    def test_craft_only_cannot_create_first_source_order_link(self):
        etag = self.source_etag()
        self.coating_user()
        before = MetalProcessingSource.objects.get(issue_line=self.line).dispatched_pieces
        response = self.client.post(f'/api/v1/metal-processing-sources/{self.line.pk}/handoffs/',
            self.handoff_payload(), format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn('首次关联', str(response.data))
        self.assertFalse(MetalProcessingOriginalHandoff.objects.filter(source__issue_line=self.line).exists())
        self.assertEqual(MetalProcessingSource.objects.get(issue_line=self.line).dispatched_pieces, before)

    def test_craft_only_can_continue_same_existing_source_order_link(self):
        first = self.create_original_handoff(4)
        etag = self.source_etag()
        member = self.coating_user()
        payload = self.handoff_payload()
        url = f'/api/v1/metal-processing-sources/{self.line.pk}/handoffs/'
        response = self.client.post(url, payload, format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(MetalProcessingSource.objects.get(pk=first.source_id).dispatched_pieces, 6)
        self.assertTrue(MetalProcessingOriginalHandoff.objects.filter(source=first.source,
            original_order_id=self.original_order, actor_employee=member, handoff_pieces=2).exists())
        replay = self.client.post(url, payload, format='json', HTTP_IF_MATCH=etag)
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(MetalProcessingOriginalHandoff.objects.filter(source=first.source).count(), 2)

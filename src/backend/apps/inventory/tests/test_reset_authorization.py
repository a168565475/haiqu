from datetime import timedelta
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.utils import timezone
from apps.inventory.reset_authorization import validate_reset_authorization


class ResetAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.identity={'host':'postgres','port':'5432','name':'haiqu_erp','oid':1234}
        self.authorization={'scope':'S9_BUSINESS_RESET','user_approval':'B->A','database':self.identity,
            'manifest_sha256':'a'*64,'operator':'S9 操作员','restore_verified':True,'backup_sha256':'b'*64,
            'maintenance_started_at':(timezone.now()-timedelta(minutes=1)).isoformat(),
            'maintenance_expires_at':(timezone.now()+timedelta(minutes=30)).isoformat()}

    def validate(self,authorization=None,identity=None):
        validate_reset_authorization(identity or self.identity,'a'*64,'S9 操作员',authorization)

    def test_missing_authorization_is_rejected(self):
        with self.assertRaises(CommandError):self.validate()

    def test_precise_authorization_is_accepted(self):
        self.validate(self.authorization)

    def test_other_host_database_or_database_oid_is_rejected(self):
        for field,value in [('host','unknown'),('port','5433'),('name','another'),('oid',5678)]:
            with self.subTest(field=field),self.assertRaises(CommandError):
                self.validate(self.authorization,{**self.identity,field:value})

    def test_changed_approval_fingerprint_or_operator_is_rejected(self):
        for field,value in [('scope','S8'),('user_approval','A'),('manifest_sha256','c'*64),('operator','其他人'),('restore_verified',False),('backup_sha256','invalid')]:
            with self.subTest(field=field),self.assertRaises(CommandError):
                self.validate({**self.authorization,field:value})

    def test_expired_future_naive_or_unbounded_window_is_rejected(self):
        changes=[{'maintenance_expires_at':(timezone.now()-timedelta(seconds=1)).isoformat()},
            {'maintenance_started_at':(timezone.now()+timedelta(seconds=10)).isoformat()},
            {'maintenance_started_at':'2026-09-19T00:00:00'},
            {'maintenance_expires_at':(timezone.now()+timedelta(hours=3)).isoformat()}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(CommandError):self.validate({**self.authorization,**change})

    def test_isolated_s8_remains_available_without_business_authorization(self):
        self.validate(identity={**self.identity,'host':'haiqu-material-flow-s3-pg','name':'material_flow_s8_s9_rehearsal'})

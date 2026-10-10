from unittest.mock import patch
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from apps.inventory import material_flow_reset as reset
from apps.inventory.tests import test_material_flow_reset as fixtures


class ResetExecutionWindowTests(TransactionTestCase):
    serialized_rollback=True
    setUp=fixtures.MaterialFlowResetTests.setUp
    run_reset=fixtures.MaterialFlowResetTests.run_reset

    def verify_expiration(self, failing_call):
        manifest=reset.preview()
        checks=0
        def check(*args,**kwargs):
            nonlocal checks
            checks+=1
            if checks==failing_call:raise CommandError('维护窗口过期')
        with patch('apps.inventory.reset_authorization.validate_reset_authorization',side_effect=check):
            with self.assertRaisesMessage(CommandError,'维护窗口过期'):self.run_reset(manifest)
        self.assertEqual(manifest['tables'],reset.table_snapshot())

    def test_expiration_after_waiting_for_locks_does_not_write(self):
        self.verify_expiration(2)

    def test_expiration_before_commit_rolls_back_data_and_audit(self):
        self.verify_expiration(3)

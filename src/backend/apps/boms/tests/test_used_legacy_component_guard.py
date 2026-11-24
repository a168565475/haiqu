from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ..component_parts import validate_used_component_structure


class UsedLegacyComponentGuardTests(SimpleTestCase):
    def legacy_line(self):
        return SimpleNamespace(pk=uuid4(), component_identity=uuid4(), component_kind='',
            section=SimpleNamespace(title='裁剪明细'), part_name='历史椅面', specification='50*40cm', unit='套')

    def test_used_legacy_cutting_cannot_be_retyped_or_replaced_by_new_typed_lines(self):
        old = self.legacy_line()
        with patch('apps.boms.component_parts._used_component_identities', return_value={old.component_identity}) as query:
            for kind in ('SEWN_PART', 'CUT_PIECE'):
                changed = deepcopy(old)
                changed.component_kind = kind
                with self.subTest(kind=kind), self.assertRaisesMessage(ValidationError, '不能原地改成新部位或裁片'):
                    validate_used_component_structure(SimpleNamespace(), [old], [changed])
            replacement = deepcopy(changed)
            replacement.pk, replacement.component_identity = uuid4(), uuid4()
            with self.assertRaisesMessage(ValidationError, '删除后用新组成替代'):
                validate_used_component_structure(SimpleNamespace(), [old], [replacement])
            self.assertIn(old.component_identity, query.call_args.args[1])

    def test_unused_conversion_and_existing_legacy_editing_keep_their_previous_behavior(self):
        old = self.legacy_line()
        changed = deepcopy(old)
        changed.component_kind = 'SEWN_PART'
        with patch('apps.boms.component_parts._used_component_identities', return_value=set()) as query:
            validate_used_component_structure(SimpleNamespace(), [old], [changed])
            query.assert_called_once()
        edited = deepcopy(old)
        edited.part_name, edited.specification = '历史名称调整', '60*40cm'
        with patch('apps.boms.component_parts._used_component_identities', return_value={old.component_identity}) as query:
            validate_used_component_structure(SimpleNamespace(), [old], [edited])
            validate_used_component_structure(SimpleNamespace(), [old], [])
            query.assert_not_called()
            # 仍保留旧行时可以继续编辑草稿，混合口径的确认由组成完整性门禁负责。
            replacement = deepcopy(changed)
            replacement.pk, replacement.component_identity = uuid4(), uuid4()
            validate_used_component_structure(SimpleNamespace(), [old], [edited, replacement])

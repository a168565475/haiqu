"""ERP 只验证执行端传输与来源契约；这里不运行任何排料算法。"""
from copy import deepcopy
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.boms.nesting_executor_contract import canonical_digest, validate_envelope
from apps.boms.nesting_storage import NestingFailure


class ExecutorEnvelopeTests(SimpleTestCase):
    def setUp(self):
        self.parameters = {'width_mm': '1680.000', 'gap_mm': '0.000', 'set_count': 1,
                           'products_per_set': 1, 'pieces': [{'piece_id': 'P001', 'name': '测试',
                               'quantity': 1, 'rotation_mode': 'fixed'}]}
        self.job = SimpleNamespace(phase='NEST', sha256='a' * 64, analysis_digest='b' * 64,
                                   parameters=self.parameters)
        self.operation = SimpleNamespace(model='configured-model')
        trace = [{'call_id': str(index), 'tool': name, 'status': 'SUCCEEDED',
                  'arguments_sha256': 'c' * 64, 'duration_ms': 1}
                 for index, name in enumerate(['inspect_source', 'search_layout', 'search_layout', 'finalize_layout'])]
        self.data = {'schema_version': 2, 'phase': 'nest', 'source_sha256': 'a' * 64,
                     'analysis_digest': 'b' * 64, 'parameters_digest': canonical_digest(self.parameters),
                     'analysis': {'unit': 'mm', 'source_unit': 'mm', 'warnings': [], 'pieces': [
                         {'id': 'P001', 'name': '测试', 'quantity': 1, 'width_mm': 10, 'height_mm': 20,
                          'area_mm2': 200, 'points': [[0, 0], [10, 0], [10, 20], [0, 0]]}]},
                     'result': {'placements': [{'piece_id': 'P001', 'copy': 0, 'x': 0, 'y': 0, 'angle': 0}],
                         'width_mm': 1680, 'gap_mm': 0, 'length_mm': 123.40000000001,
                         'set_count': 1, 'products_per_set': 1, 'product_quantity': 1,
                         'consumption_m': '0.12340000000001', 'consumption_rounded_m': '0.1235',
                         'utilization_percent': 1, 'validation': {'passed': True, 'quantities_valid': True,
                             'bounds_valid': True, 'rotations_valid': True, 'overlap_free': True, 'piece_count': 1}},
                     'artifacts': [{'name': name, 'size_bytes': 8, 'sha256': 'd' * 64, 'content_type': media}
                                   for name, media in [('layout.svg', 'image/svg+xml'), ('layout.dxf', 'application/dxf')]],
                     'execution': {'engine': 'CODEX_TOOLS', 'toolkit_version': '1', 'model': 'configured-model',
                                   'tool_calls': trace, 'guided_attempts': 1}}

    def test_gateway_preserves_executor_values_without_recalculating(self):
        expected = deepcopy(self.data)
        validate_envelope(self.job, self.operation, self.data)
        self.assertEqual(self.data, expected)

    def test_large_valid_analysis_area_uses_executor_limit(self):
        data = deepcopy(self.data)
        data['analysis']['pieces'][0].update(width_mm=100000, height_mm=100001, area_mm2=10000100000)
        validate_envelope(self.job, self.operation, data)

    def test_wrong_source_or_parameters_cannot_be_used(self):
        for field in ('source_sha256', 'analysis_digest', 'parameters_digest'):
            with self.subTest(field=field):
                invalid = deepcopy(self.data)
                invalid[field] = 'e' * 64
                with self.assertRaises(NestingFailure):
                    validate_envelope(self.job, self.operation, invalid)

    def test_model_statement_without_actual_tool_chain_is_not_a_result(self):
        for change in ({'engine': 'MODEL_TEXT'}, {'tool_calls': []}, {'guided_attempts': 0}):
            with self.subTest(change=change):
                invalid = deepcopy(self.data)
                invalid['execution'].update(change)
                with self.assertRaises(NestingFailure):
                    validate_envelope(self.job, self.operation, invalid)

    def test_duplicate_or_unapproved_artifact_cannot_be_saved(self):
        for name in ('../source.dxf', 'source.dxf', 'layout.svg'):
            with self.subTest(name=name):
                invalid = deepcopy(self.data)
                invalid['artifacts'][1]['name'] = name
                with self.assertRaises(NestingFailure):
                    validate_envelope(self.job, self.operation, invalid)

    def test_extraction_is_not_a_finished_layout(self):
        job = SimpleNamespace(phase='EXTRACT', sha256='a' * 64, analysis_digest='', parameters={})
        invalid = deepcopy(self.data)
        invalid['phase'] = 'extract'
        invalid['parameters_digest'] = ''
        with self.assertRaises(NestingFailure):
            validate_envelope(job, self.operation, invalid)

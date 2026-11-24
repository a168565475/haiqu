import asyncio
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ezdxf

from codex_runtime.dxf_tools import DxfToolSession, ToolSessionError
from codex_runtime.dxf_tools.session import digest


def source_payload(phase='extract', drawing_unit=4):
    document = ezdxf.new('R2010')
    document.units = drawing_unit
    document.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    output = io.StringIO()
    document.write(output)
    source = output.getvalue().encode()
    payload = {'schema_version': 2, 'phase': phase, 'source': {
        'data_base64': base64.b64encode(source).decode(), 'size_bytes': len(source),
        'sha256': hashlib.sha256(source).hexdigest(), 'unit': 'mm'}}
    return payload


class DxfToolTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path('/tmp/haiqu-dxf-executor-20261105-tests')
        if cls.root.exists():
            raise RuntimeError('Registered isolated test directory must not already exist')
        cls.root.mkdir(mode=0o700)
        cls.old_tempdir = tempfile.tempdir
        tempfile.tempdir = str(cls.root)

    @classmethod
    def tearDownClass(cls):
        tempfile.tempdir = cls.old_tempdir
        # A leaked session must fail rather than be silently hidden by recursive cleanup.
        cls.root.rmdir()

    async def test_extract_requires_real_tools_and_cleans_source(self):
        session = DxfToolSession(source_payload())
        with self.assertRaises(ToolSessionError):
            session.completed_result()
        async with session:
            self.assertEqual({row['name'] for row in session.tool_definitions()},
                             {'inspect_source', 'finalize_layout'})
            inspected = await session.call('inspect_source', {}, 'inspect-1')
            self.assertEqual(len(inspected['analysis']['pieces']), 1)
            self.assertEqual(inspected['analysis']['pieces'][0]['width_mm'], 100)
            await session.call('finalize_layout', {}, 'finalize-1')
            data, artifacts = session.completed_result()
            self.assertEqual(data['phase'], 'extract')
            self.assertEqual(artifacts, {})
            self.assertEqual([row['tool'] for row in data['execution']['tool_calls']],
                             ['inspect_source', 'finalize_layout'])
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_rejects_forged_source_before_any_execution(self):
        payload = source_payload()
        payload['source']['sha256'] = '0' * 64
        with self.assertRaises(ToolSessionError) as error:
            DxfToolSession(payload)
        self.assertEqual(error.exception.code, 'SOURCE_CHANGED')

    async def test_source_and_parameter_envelope_is_strict(self):
        original = source_payload()
        mutations = [lambda p: p.update(extra='ignored'),
                     lambda p: p['source'].update(path='/etc/passwd'),
                     lambda p: p['source'].update(size_bytes=True),
                     lambda p: p['source'].update(data_base64='!!!'),
                     lambda p: p['source'].update(unit='feet'),
                     lambda p: p.update(schema_version=True)]
        for mutate in mutations:
            payload = copy.deepcopy(original)
            mutate(payload)
            with self.subTest(payload=payload.keys()), self.assertRaises(ToolSessionError):
                DxfToolSession(payload)

    async def test_parameter_types_and_quantities_are_checked_before_execution(self):
        for key, value in [('set_count', True), ('products_per_set', 0), ('width_mm', 'NaN'),
                           ('gap_mm', -1), ('pieces', [{'piece_id': 'P001', 'quantity': 1, 'rotation_mode': []}])]:
            payload = source_payload('nest')
            payload.update(analysis_digest='0' * 64, parameters=self.parameters())
            payload['parameters'][key] = value
            with self.subTest(key=key), self.assertRaises(ToolSessionError):
                DxfToolSession(payload)

    async def test_unknown_source_unit_keeps_exact_error_for_user_correction(self):
        payload = source_payload(drawing_unit=0)
        payload['source']['unit'] = 'auto'
        async with DxfToolSession(payload) as session:
            with self.assertRaises(ToolSessionError) as error:
                await session.call('inspect_source', {}, 'unit')
            self.assertEqual(error.exception.code, 'DXF_UNIT_UNKNOWN')
            self.assertEqual(session.failure_code, 'DXF_UNIT_UNKNOWN')
            with self.assertRaises(ToolSessionError) as final_error:
                session.completed_result()
            self.assertEqual(final_error.exception.code, 'DXF_UNIT_UNKNOWN')

    async def test_stale_analysis_cannot_be_used_for_nesting(self):
        payload = source_payload('nest')
        payload.update(analysis_digest='0' * 64, parameters=self.parameters())
        async with DxfToolSession(payload) as session:
            with self.assertRaises(ToolSessionError) as error:
                await session.call('inspect_source', {}, 'stale')
            self.assertEqual(error.exception.code, 'SOURCE_CHANGED')
            self.assertEqual(session.failure_code, 'SOURCE_CHANGED')
            with self.assertRaises(ToolSessionError) as error:
                session.completed_result()
            self.assertEqual(error.exception.code, 'SOURCE_CHANGED')

    async def test_file_change_is_detected_before_finalization(self):
        async with DxfToolSession(source_payload()) as session:
            await session.call('inspect_source', {}, 'i')
            path = session.root / 'source.dxf'
            path.chmod(0o600)
            path.write_bytes(b'changed')
            with self.assertRaises(ToolSessionError) as error:
                await session.call('finalize_layout', {}, 'f')
            self.assertEqual(error.exception.code, 'SOURCE_CHANGED')
            with self.assertRaises(ToolSessionError):
                session.completed_result()

    async def test_duplicate_call_ids_cannot_reexecute_tools(self):
        async with DxfToolSession(source_payload()) as session:
            await session.call('inspect_source', {}, 'same')
            with self.assertRaises(ToolSessionError):
                await session.call('finalize_layout', {}, 'same')
            with self.assertRaises(ToolSessionError):
                session.completed_result()

    async def test_cancel_kills_active_child_and_cleans_private_directory(self):
        async with DxfToolSession(source_payload()) as session:
            task = asyncio.create_task(session.call('inspect_source', {}, 'cancel'))
            async with asyncio.timeout(10):
                while session._process is None:
                    await asyncio.sleep(.005)
            process = session._process
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertIsNotNone(process.returncode)
            self.assertIsNone(session._process)
            self.assertEqual(session.failure_code, 'INTERRUPTED')
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_hard_timeout_reports_failure_and_reaps_child(self):
        async with DxfToolSession(source_payload()) as session:
            original = session._run

            async def short_run(operation, data, _hard_timeout, **kwargs):
                return await original(operation, data, .001, **kwargs)

            with patch.object(session, '_run', side_effect=short_run):
                with self.assertRaises(ToolSessionError) as error:
                    await session.call('inspect_source', {}, 'timeout')
            self.assertEqual(error.exception.code, 'NEST_TIMEOUT')
            self.assertIsNone(session._process)
            self.assertEqual(session._calls[-1]['status'], 'TIMEOUT')

    async def test_invalid_dxf_keeps_actionable_failure_code(self):
        payload = source_payload()
        raw = b'not a dxf document'
        payload['source'].update(data_base64=base64.b64encode(raw).decode(), size_bytes=len(raw),
                                 sha256=hashlib.sha256(raw).hexdigest())
        async with DxfToolSession(payload) as session:
            with self.assertRaises(ToolSessionError) as error:
                await session.call('inspect_source', {}, 'invalid')
            self.assertEqual(error.exception.code, 'DXF_INVALID')
            with self.assertRaises(ToolSessionError) as final_error:
                session.completed_result()
            self.assertEqual(final_error.exception.code, 'DXF_INVALID')

    async def test_no_algorithm_is_run_before_inspect_tool(self):
        async with DxfToolSession(source_payload()) as session:
            with patch.object(session, '_run', side_effect=AssertionError('No premature process')):
                with self.assertRaises(ToolSessionError):
                    await session.call('finalize_layout', {}, 'premature')
            with self.assertRaises(ToolSessionError):
                session.completed_result()

    async def test_complete_nest_exports_matching_artifacts_and_real_trace(self):
        payload = source_payload()
        async with DxfToolSession(payload) as extraction:
            summary = await extraction.call('inspect_source', {}, 'i')
        payload.update(phase='nest', analysis_digest=summary['analysis_digest'], parameters=self.parameters())
        async with DxfToolSession(payload) as session:
            await session.call('inspect_source', {}, 'inspect')
            baseline = await session.call('search_layout', {'mode': 'baseline', 'proposal': None}, 'base')
            with self.assertRaises(ToolSessionError):
                await session.call('finalize_layout', {}, 'too-early')
            context = baseline['search_context']
            proposal = {'schema_version': 1, 'constraint_fingerprint': context['constraint_fingerprint'],
                        'plans': [{'reason': '试横向排列', 'order': [
                            {'instance_id': item['instance_id'], 'angles': [0]}
                            for item in context['instances']]}]}
            await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'guided')
            await session.call('finalize_layout', {}, 'final')
            data, artifacts = session.completed_result()
            self.assertEqual(set(artifacts), {'layout.svg', 'layout.dxf'})
            for item in data['artifacts']:
                self.assertEqual(hashlib.sha256(artifacts[item['name']]).hexdigest(), item['sha256'])
                self.assertEqual(len(artifacts[item['name']]), item['size_bytes'])
            self.assertEqual(data['result']['validation']['pair_checks'], 1)
            self.assertEqual(data['result']['consumption_rounded_m'], '0.0250')
            self.assertEqual(data['execution']['guided_attempts'], 1)
            self.assertEqual(data['execution']['tool_calls'][-1]['call_id'], 'final')
            self.assertEqual(data['execution']['engine'], 'CODEX_TOOLS')
            self.assertEqual(data['parameters_digest'], digest(payload['parameters']))
            self.assertTrue(all(row['status'] in {'SUCCEEDED', 'FAILED', 'TIMEOUT'}
                                for row in data['execution']['tool_calls']))

    async def _nested_session(self):
        payload = source_payload()
        async with DxfToolSession(payload) as extraction:
            summary = await extraction.call('inspect_source', {}, 'extract')
        payload.update(phase='nest', analysis_digest=summary['analysis_digest'], parameters=self.parameters())
        session = DxfToolSession(payload)
        self.addAsyncCleanup(session.close)
        await session.call('inspect_source', {}, 'inspect')
        baseline = await session.call('search_layout', {'mode': 'baseline', 'proposal': None}, 'baseline')
        context = baseline['search_context']
        proposal = {'schema_version': 1, 'constraint_fingerprint': context['constraint_fingerprint'],
                    'plans': [{'reason': '', 'order': [{'instance_id': row['instance_id'], 'angles': [0]}
                              for row in context['instances']]}]}
        return session, proposal

    async def test_invalid_plan_cannot_finalize_and_guided_calls_are_bounded(self):
        session, proposal = await self._nested_session()
        invalid = copy.deepcopy(proposal)
        invalid['plans'][0]['order'].pop()
        with self.assertRaises(ToolSessionError) as error:
            await session.call('search_layout', {'mode': 'guided', 'proposal': invalid}, 'bad')
        self.assertEqual(error.exception.code, 'CODEX_INVALID_PROPOSAL')
        with self.assertRaises(ToolSessionError):
            await session.call('finalize_layout', {}, 'early')
        await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'good1')
        await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'good2')
        with self.assertRaises(ToolSessionError) as error:
            await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'fourth')
        self.assertEqual(error.exception.code, 'TOOL_LIMIT')
        await session.call('finalize_layout', {}, 'final')
        data, _ = session.completed_result()
        self.assertEqual(data['execution']['guided_attempts'], 3)

    async def test_guided_timeout_keeps_checked_baseline_with_honest_status(self):
        session, proposal = await self._nested_session()
        baseline_length = session._best['length_mm']
        with patch.object(session, '_run', side_effect=ToolSessionError('NEST_TIMEOUT')):
            response = await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'timeout')
        self.assertEqual(response['status'], 'TIMED_OUT')
        self.assertEqual(session._calls[-1]['status'], 'TIMEOUT')
        await session.call('finalize_layout', {}, 'final')
        data, _ = session.completed_result()
        self.assertEqual(data['result']['length_mm'], baseline_length)
        self.assertEqual(data['result']['optimization']['status'], 'UNCHANGED')
        self.assertTrue(data['result']['optimization']['timed_out'])

    async def test_oversized_artifact_does_not_publish_success(self):
        session, proposal = await self._nested_session()
        await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'guided')
        with patch('codex_runtime.dxf_tools.session.MAX_ARTIFACT', 10):
            with self.assertRaises(ToolSessionError) as error:
                await session.call('finalize_layout', {}, 'oversize')
        self.assertEqual(error.exception.code, 'RESULT_LIMIT')
        with self.assertRaises(ToolSessionError):
            session.completed_result()

    async def test_internal_algorithm_error_is_not_silently_converted_to_success(self):
        async with DxfToolSession(source_payload()) as session:
            with patch.object(session, '_run', side_effect=RuntimeError('internal test failure')):
                with self.assertRaisesRegex(RuntimeError, 'internal test failure'):
                    await session.call('inspect_source', {}, 'broken')
            with self.assertRaises(ToolSessionError):
                session.completed_result()

    async def test_child_internal_error_retains_bounded_code_locations(self):
        async with DxfToolSession(source_payload()) as session:
            with self.assertRaisesRegex(RuntimeError, r'ValueError.*runner.py'):
                await session._run('unknown_internal_operation', {}, 45)

    async def test_child_environment_uses_own_home_and_no_auth_or_business_environment(self):
        original = asyncio.create_subprocess_exec
        async with DxfToolSession(source_payload()) as session:
            with patch('codex_runtime.dxf_tools.session.asyncio.create_subprocess_exec', wraps=original) as spawn:
                await session.call('inspect_source', {}, 'environment')
            environment = spawn.call_args.kwargs['env']
            self.assertEqual(environment['HOME'], str(session.root))
            self.assertEqual(environment['XDG_CONFIG_HOME'], str(session.root / 'config'))
            self.assertEqual(environment['OPENBLAS_NUM_THREADS'], '1')
            self.assertEqual(environment['OMP_NUM_THREADS'], '1')
            self.assertNotIn('CODEX_HOME', environment)
            self.assertNotIn('HTTP_PROXY', environment)
            self.assertNotIn('DATABASE_URL', environment)

    @staticmethod
    def parameters():
        return {'width_mm': '200', 'gap_mm': '0', 'set_count': 2, 'products_per_set': 1,
                'pieces': [{'piece_id': 'P001', 'quantity': 1, 'rotation_mode': 'quarter_turn'}]}


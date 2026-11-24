import copy
import http.client
import io
import json
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.ai_production_import.client import _model_source, recognize
from apps.ai_production_import.errors import AiOutputInvalid, AiProviderRequestFailed


def valid_payload(source_id='s1'):
    value = lambda text: {'value': text, 'status': 'EXTRACTED', 'source_ids': [source_id], 'note': ''}
    return {
        'task': {'task_number': value('HT1'), 'contract_number': value('C1'), 'order_date': value('2026-11-11'),
                 'delivery_date': value('2026-11-20'), 'special_requirements': value('')},
        'products': [{'product_key': 'P1', 'name': value('椅子'), 'specification': value('标准'),
                      'color': value('黑'), 'quantity': value('1'), 'unit': value('件'),
                      'special_requirements': value('')}],
        'boms': [{'product_key': 'P1', 'lines': []}], 'issues': [],
    }


def source_fixture():
    return {
        'source_index': {'src_1': {'kind': 'cell', 'sheet': 'Sheet1', 'ref': 'A1'}},
        'images': [],
        'sheets': [{'name': 'Sheet1', 'cells': [{'ref': 'A1', 'text': 'HT1', 'source_id': 'src_1'}]}],
    }


class Response:
    status = 200
    headers = {'Content-Type': 'application/json'}

    def __init__(self, payload=None, raw=None):
        if payload is None:
            payload = {'output': [{'content': [{'type': 'output_text', 'text': json.dumps(valid_payload())}]}]}
        payload = {'status': 'completed', **payload}
        self.data = raw if raw is not None else json.dumps(payload).encode()

    def read(self, size=-1):
        return self.data[:size] if size >= 0 else self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def stream_event(kind, **fields):
    return f'event: {kind}\ndata: {json.dumps({"type": kind, **fields})}\n\n'.encode()


def completed_event(source_id='s1'):
    return stream_event('response.completed', response={
        'status': 'completed',
        'output': [{'content': [{'type': 'output_text', 'text': json.dumps(valid_payload(source_id))}]}],
    })


class StreamResponse(Response):
    headers = {'Content-Type': 'text/event-stream; charset=utf-8'}

    def __init__(self, raw):
        self.stream = io.BytesIO(raw)
        self.read_sizes = []

    def readline(self, size):
        self.read_sizes.append(size)
        return self.stream.readline(size)


class ClientTests(unittest.TestCase):
    def test_recognition_normalizes_excel_task_date_before_preview(self):
        payload = valid_payload()
        payload['task']['delivery_date']['value'] = 46305
        source = source_fixture()
        source['sheets'][0]['cells'][0].update(text='46305', type='n', num_format_id='14')
        response = Response({'output': [{'content': [{'type': 'output_text', 'text': json.dumps(payload)}]}]})
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
            result, _ = self.call(source=source)
        self.assertEqual(result['task']['delivery_date']['value'], '2026-10-10')
        self.assertIn('46305', result['task']['delivery_date']['note'])

    def test_recognition_recovers_omitted_cut_count_from_actual_cells_before_returning(self):
        from apps.ai_production_import.client import _prepare_model_source
        from apps.ai_production_import.tests.test_field_coverage import controlled, source_sheet, tube_line

        source = controlled(source_sheet())
        _, identifiers = _prepare_model_source(source)
        aliases = {original: short for short, original in identifiers.items()}
        payload = valid_payload("sheet-a-D10")
        line = tube_line()
        line["erp_fields"] = [{"field": key, "value": value} for key, value in line["erp_fields"].items()]
        payload["boms"][0]["lines"] = [line]

        def shorten(value):
            if isinstance(value, dict):
                return {key: [aliases[item] for item in child] if key == "source_ids" else shorten(child)
                        for key, child in value.items()}
            if isinstance(value, list):
                return [shorten(item) for item in value]
            return value

        response = Response({"output": [{"content": [{"type": "output_text", "text": json.dumps(shorten(payload))}]}]})
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
            result, _ = self.call(source=source)
        recovered = result["boms"][0]["lines"][0]
        self.assertEqual(recovered["erp_fields"]["tube_cut_piece_count"]["value"], 11)
        self.assertIn("sheet-a-O10", recovered["erp_fields"]["tube_cut_piece_count"]["source_ids"])
        self.assertIn("切999支", recovered["raw_content"]["value"])
        self.assertEqual(result["issues"], [])

    def call(self, *, source=None, model='gpt-6-astra', images=None, timeout_seconds=600):
        return recognize(
            credentials={'api_key': 'sk-test', 'model': model, 'base_url': 'https://api.openai.com/v1'},
            controlled={'source': source if source is not None else source_fixture(), 'image_parts': images or {}},
            timeout_seconds=timeout_seconds,
        )

    def test_rejects_invalid_response_before_write(self):
        payload = {'output': [{'content': [{'type': 'output_text', 'text': '{}'}]}]}
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=Response(payload)):
            with self.assertRaises(AiOutputInvalid):
                self.call()

    def test_request_restores_short_sources_and_uses_structured_output(self):
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=Response()) as send:
            result, model = self.call()
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(model, 'gpt-6-astra')
        self.assertEqual(result['products'][0]['product_key'], 'P1')
        self.assertEqual(result['task']['task_number']['source_ids'], ['src_1'])
        self.assertEqual(request.headers['Authorization'], 'Bearer sk-test')
        self.assertEqual(body['text']['format']['type'], 'json_schema')
        self.assertEqual(body['reasoning'], {'effort': 'xhigh'})
        self.assertIs(body['stream'], True)
        self.assertEqual(request.headers['Accept'], 'text/event-stream')
        self.assertGreater(send.call_args.kwargs['timeout'], 599)
        self.assertLessEqual(send.call_args.kwargs['timeout'], 600)
        sent = json.loads(body['input'][1]['content'][0]['text'])
        self.assertEqual(sent['sheets'][0]['cells'][0]['source_id'], 's1')
        self.assertNotIn('source_index', sent)
        self.assertNotIn('src_1', body['input'][1]['content'][0]['text'])

    def test_other_models_do_not_receive_unsupported_reasoning_option(self):
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=Response()) as send:
            self.call(model='other-model')
        self.assertNotIn('reasoning', json.loads(send.call_args.args[0].data))

    def test_document_reasoning_uses_its_own_setting(self):
        for model, selected, expected in (
            ('gpt-6-astra', 'auto', 'xhigh'),
            ('gpt-6-astra', 'high', 'high'),
            ('gpt-6-astra', 'max', 'max'),
            ('custom-model', 'xhigh', 'xhigh'),
            ('custom-model', 'auto', None),
        ):
            with self.subTest(model=model, selected=selected), \
                 patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=Response()) as send:
                recognize(
                    credentials={'api_key': 'test', 'model': model, 'base_url': 'https://example.test/v1',
                                 'document_reasoning_effort': selected, 'material_reasoning_effort': 'medium'},
                    controlled={'source': source_fixture()},
                )
                body = json.loads(send.call_args.args[0].data)
                self.assertEqual(body.get('reasoning'), {'effort': expected} if expected else None)

    def test_all_cells_dates_formulas_comments_and_merges_preserved_without_mutating_source(self):
        source = source_fixture()
        sheet = source['sheets'][0]
        sheet['source_id'] = 'src_sheet'
        source['source_index']['src_sheet'] = {'kind': 'sheet_title'}
        sheet['cells'][0].update(type='n', formula='SUM(B2:B3)', cache='46338',
                                 formula_attributes={'t': 'shared', 'si': '0', 'ref': 'A1:A3'},
                                 num_format_id=14, num_format='yyyy-mm-dd', style=4)
        sheet['cells'].append({'ref': 'B2', 'text': '原样保留', 'source_id': 'src_2'})
        source['source_index']['src_2'] = {'kind': 'cell'}
        sheet['comments'] = [{'ref': 'B2', 'text': '业务批注', 'source_id': 'src_comment', 'part': 'unneeded-part'}]
        source['source_index']['src_comment'] = {'kind': 'comment'}
        sheet['merged_cells'] = ['A1:C1']
        source['date1904'] = '1'
        original = copy.deepcopy(source)
        sent = _model_source(source)
        self.assertEqual(source, original)
        self.assertEqual(sent['date1904'], '1')
        self.assertEqual(len(sent['sheets'][0]['cells']), 2)
        first = sent['sheets'][0]['cells'][0]
        for key in ('ref', 'type', 'text', 'formula', 'cache', 'formula_attributes', 'num_format_id', 'num_format'):
            self.assertEqual(first[key], sheet['cells'][0][key])
        self.assertNotIn('style', first)
        self.assertEqual(sent['sheets'][0]['merged_cells'], ['A1:C1'])
        self.assertEqual(sent['sheets'][0]['comments'][0]['text'], '业务批注')
        self.assertNotIn('part', sent['sheets'][0]['comments'][0])

    def test_images_data_uris_and_picture_formulas_are_not_sent(self):
        source = source_fixture()
        source['images'] = [{'id': 'image_001', 'bytes': 'private-image-data'}]
        source['sheets'][0]['pictures'] = [{'embed_image_id': 'image_001'}]
        source['sheets'][0]['cells'].extend([
            {'ref': 'B1', 'text': 'data:image/png;base64,private-image-data', 'source_id': 'src_2'},
            {'ref': 'C1', 'text': '#VALUE!', 'formula': '_xlfn.DISPIMG("private-image-id",1)', 'cache': '#VALUE!', 'source_id': 'src_3'},
            {'ref': 'D1', 'text': '=IMAGE("https://images.invalid/private.png")', 'source_id': 'src_4'},
        ])
        source['source_index'].update({sid: {'kind': 'cell'} for sid in ('src_2', 'src_3', 'src_4')})
        source['source_index']['src_image'] = {'kind': 'image_asset', 'part': 'private-image-part'}
        original = copy.deepcopy(source)
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=Response()) as send:
            self.call(source=source, images={'image_001': ('image/png', b'private-image-data')})
        body = json.loads(send.call_args.args[0].data)
        content = body['input'][1]['content']
        self.assertEqual([item['type'] for item in content], ['input_text'])
        sent = json.loads(content[0]['text'])
        self.assertNotIn('images', sent)
        self.assertNotIn('pictures', sent['sheets'][0])
        self.assertEqual(len(sent['sheets'][0]['cells']), 4)
        self.assertTrue(all(c['image_omitted'] for c in sent['sheets'][0]['cells'][1:]))
        for secret in ('data:image/', 'private-image-', 'DISPIMG', 'https://images.invalid', 'src_image'):
            self.assertNotIn(secret, content[0]['text'])
        self.assertEqual(source, original)

    def test_model_cannot_cite_unsent_image_or_original_long_id(self):
        source = source_fixture()
        source['images'] = [{'id': 'image_001', 'source_id': 'src_image'}]
        source['source_index']['src_image'] = {'kind': 'image_asset'}
        for invalid_id in ('image_001', 'src_image', 'src_1', 's99', 1):
            with self.subTest(source_id=invalid_id):
                payload = {'output': [{'content': [{'type': 'output_text', 'text': json.dumps(valid_payload(invalid_id))}]}]}
                with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=Response(payload)):
                    with self.assertRaises(AiOutputInvalid) as error:
                        self.call(source=source)
                self.assertEqual(error.exception.code, 'OPENAI_OUTPUT_SOURCE_INVALID')

    def test_http_failures_are_classified_without_exposing_upstream_body(self):
        expected = {400: 'OPENAI_BAD_REQUEST', 401: 'OPENAI_AUTH_FAILED', 403: 'OPENAI_ACCESS_DENIED',
                    404: 'OPENAI_MODEL_NOT_FOUND', 429: 'OPENAI_RATE_LIMITED', 500: 'OPENAI_SERVER_ERROR'}
        for status, code in expected.items():
            with self.subTest(status=status):
                upstream = urllib.error.HTTPError('https://api.openai.com/v1/responses', status,
                                                  'private-response', {}, io.BytesIO(b'sk-secret upstream-content'))
                with patch('apps.ai_production_import.client.urllib.request.urlopen', side_effect=upstream):
                    with self.assertRaises(AiProviderRequestFailed) as error:
                        self.call()
                self.assertEqual(error.exception.code, code)
                self.assertNotIn('sk-secret', str(error.exception))
                self.assertNotIn('private-response', str(error.exception))
                self.assertEqual(upstream.fp.tell(), 0)

    def test_timeout_and_network_failures_are_distinct(self):
        for reason, code in ((TimeoutError(), 'OPENAI_TIMEOUT'),
                             (urllib.error.URLError(TimeoutError()), 'OPENAI_TIMEOUT'),
                             (urllib.error.URLError('DNS unavailable'), 'OPENAI_NETWORK_ERROR'),
                             (http.client.RemoteDisconnected(), 'OPENAI_NETWORK_ERROR'),
                             (http.client.IncompleteRead(b'partial'), 'OPENAI_NETWORK_ERROR'),
                             (ConnectionResetError(), 'OPENAI_NETWORK_ERROR'),
                             (OSError('network unavailable'), 'OPENAI_NETWORK_ERROR')):
            with self.subTest(reason=type(reason).__name__):
                with patch('apps.ai_production_import.client.urllib.request.urlopen', side_effect=reason):
                    with self.assertRaises(AiProviderRequestFailed) as error:
                        self.call()
                self.assertEqual(error.exception.code, code)

    def test_stream_uses_only_completed_response_and_restores_sources(self):
        response = StreamResponse(
            b': heartbeat\n\n' + stream_event('response.output_text.delta', delta='not final JSON') + completed_event()
        )
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
            result, model = self.call()
        self.assertEqual(model, 'gpt-6-astra')
        self.assertEqual(result['task']['task_number']['source_ids'], ['src_1'])
        self.assertTrue(response.read_sizes)
        self.assertTrue(all(0 < size <= 2 * 1024 * 1024 + 1 for size in response.read_sizes))

    def test_completed_stream_still_validates_source_references(self):
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=StreamResponse(completed_event('s99'))):
            with self.assertRaises(AiOutputInvalid) as error:
                self.call()
        self.assertEqual(error.exception.code, 'OPENAI_OUTPUT_SOURCE_INVALID')

    def test_valid_stream_can_exceed_single_event_limit_in_total(self):
        final_event = completed_event()
        event_limit = len(final_event) + 10
        response = StreamResponse(b': heartbeat\n\n' * event_limit + final_event)
        with patch('apps.ai_production_import.client.MAX_RESPONSE_BYTES', event_limit), \
             patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
            result, _ = self.call()
        self.assertEqual(result['task']['task_number']['value'], 'HT1')

    def test_nonstream_response_must_also_have_completed_status(self):
        for status in (None, 'in_progress', 'queued'):
            with self.subTest(status=status):
                response = Response({'status': status, 'output': [
                    {'content': [{'type': 'output_text', 'text': json.dumps(valid_payload())}]},
                ]})
                with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
                    with self.assertRaises(AiOutputInvalid) as error:
                        self.call()
                self.assertEqual(error.exception.code, 'OPENAI_RESPONSE_INCOMPLETE')

    def test_stream_eof_never_accepts_partial_output(self):
        for raw in (
            b'',
            stream_event('response.output_text.delta', delta=json.dumps(valid_payload())),
            completed_event().rstrip(b'\n'),
            b'data: [DONE]\n\n',
        ):
            with self.subTest(size=len(raw)):
                with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=StreamResponse(raw)):
                    with self.assertRaises(AiOutputInvalid) as error:
                        self.call()
                self.assertEqual(error.exception.code, 'OPENAI_RESPONSE_INTERRUPTED')

    def test_model_output_limit_is_distinct_from_transport_interruption(self):
        response = StreamResponse(stream_event('response.incomplete', response={
            'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
        }))
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
            with self.assertRaises(AiOutputInvalid) as error:
                self.call()
        self.assertEqual(error.exception.code, 'OPENAI_OUTPUT_LIMIT')

    def test_stream_failure_refusal_and_incomplete_never_become_success(self):
        cases = (
            ('error', AiProviderRequestFailed, 'OPENAI_SERVER_ERROR'),
            ('response.failed', AiProviderRequestFailed, 'OPENAI_SERVER_ERROR'),
            ('response.incomplete', AiOutputInvalid, 'OPENAI_RESPONSE_INCOMPLETE'),
            ('response.refusal.delta', AiOutputInvalid, 'OPENAI_RESPONSE_REFUSED'),
            ('response.refusal.done', AiOutputInvalid, 'OPENAI_RESPONSE_REFUSED'),
        )
        for kind, exception, code in cases:
            with self.subTest(kind=kind):
                response = StreamResponse(stream_event(kind, message='sk-secret private-response') + completed_event())
                with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
                    with self.assertRaises(exception) as error:
                        self.call()
                self.assertEqual(error.exception.code, code)
                self.assertNotIn('sk-secret', str(error.exception))
                self.assertNotIn('private-response', str(error.exception))

    def test_stream_completed_requires_complete_valid_response(self):
        for raw, code in (
            (stream_event('response.completed', response={'status': 'incomplete', 'output': []}), 'OPENAI_RESPONSE_INCOMPLETE'),
            (stream_event('response.completed'), 'OPENAI_RESPONSE_INCOMPLETE'),
            (b'data: not-json\n\n', 'OPENAI_RESPONSE_JSON_INVALID'),
            (b'data: \xff\n\n', 'OPENAI_RESPONSE_JSON_INVALID'),
        ):
            with self.subTest(code=code):
                with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=StreamResponse(raw)):
                    with self.assertRaises(AiOutputInvalid) as error:
                        self.call()
                self.assertEqual(error.exception.code, code)

    def test_response_size_limit_applies_to_one_line_and_total_stream(self):
        for response in (
            Response(raw=b'x' * 129),
            StreamResponse(b'data: ' + b'x' * 129 + b'\n\n'),
            StreamResponse(b'data: ' + b'x' * 60 + b'\n' + b'data: ' + b'x' * 60 + b'\n\n'),
            StreamResponse(b': heartbeat\n\n' * 20),
        ):
            with self.subTest(response=type(response).__name__):
                with patch('apps.ai_production_import.client.MAX_RESPONSE_BYTES', 128), \
                     patch('apps.ai_production_import.client.MAX_STREAM_BYTES', 256), \
                     patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
                    with self.assertRaises(AiProviderRequestFailed) as error:
                        self.call()
                self.assertEqual(error.exception.code, 'OPENAI_RESPONSE_TOO_LARGE')

    def test_stream_disconnect_during_read_is_network_failure(self):
        response = StreamResponse(b'')
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response), \
             patch.object(response, 'readline', side_effect=http.client.RemoteDisconnected()):
            with self.assertRaises(AiProviderRequestFailed) as error:
                self.call()
        self.assertEqual(error.exception.code, 'OPENAI_NETWORK_ERROR')

    def test_each_stream_read_uses_remaining_total_timeout(self):
        response = StreamResponse(completed_event())
        sock = Mock()
        response.fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock))
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response) as send, \
             patch('apps.ai_production_import.client.time.monotonic', side_effect=[0, 0, 1, 2, 3, 4, 5, 6]):
            self.call(timeout_seconds=7)
        self.assertEqual(send.call_args.kwargs['timeout'], 7)
        self.assertEqual([call.args[0] for call in sock.settimeout.call_args_list], [6, 4, 2])

    def test_stream_cannot_finish_after_total_timeout(self):
        with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=StreamResponse(completed_event())), \
             patch('apps.ai_production_import.client.time.monotonic', side_effect=[0, 1, 301]):
            with self.assertRaises(AiProviderRequestFailed) as error:
                self.call(timeout_seconds=300)
        self.assertEqual(error.exception.code, 'OPENAI_TIMEOUT')

    def test_refusal_incomplete_and_bad_json_fail_before_preview(self):
        for response, code in (
            (Response({'status': 'incomplete', 'output': []}), 'OPENAI_RESPONSE_INCOMPLETE'),
            (Response({'output': [{'content': [{'type': 'refusal', 'refusal': 'not available'}]}]}), 'OPENAI_RESPONSE_REFUSED'),
            (Response(raw=b'not-json'), 'OPENAI_RESPONSE_JSON_INVALID'),
        ):
            with self.subTest(code=code):
                with patch('apps.ai_production_import.client.urllib.request.urlopen', return_value=response):
                    with self.assertRaises(AiOutputInvalid) as error:
                        self.call()
                self.assertEqual(error.exception.code, code)

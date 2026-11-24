"""执行端回传契约：只核对来源、参数及传输结构，不执行几何或单耗计算。"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

from .nesting_storage import MAX_JSON_BYTES, NestingFailure


ARTIFACT_TYPES = {'layout.svg': 'image/svg+xml', 'layout.dxf': 'application/dxf'}
HEX64 = re.compile(r'[0-9a-f]{64}')


def require(condition):
    if not condition:
        raise NestingFailure('EXECUTOR_RESULT_INVALID')


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def finite(value, low=0, high=10000000000):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate_analysis(analysis):
    require(isinstance(analysis, dict) and analysis.get('unit') == 'mm')
    pieces = analysis.get('pieces')
    require(isinstance(pieces, list) and 1 <= len(pieces) <= 160)
    seen, point_count = set(), 0
    for piece in pieces:
        require(isinstance(piece, dict))
        key = piece.get('id')
        require(isinstance(key, str) and re.fullmatch(r'P\d{3}', key) and key not in seen)
        seen.add(key)
        require(isinstance(piece.get('name'), str) and 1 <= len(piece['name']) <= 80)
        require(type(piece.get('quantity')) is int and 1 <= piece['quantity'] <= 1000000)
        require(all(finite(piece.get(field), .000001, 10000000) for field in ('width_mm', 'height_mm')))
        require(finite(piece.get('area_mm2'), .000001, 100000000000000))
        points = piece.get('points')
        require(isinstance(points, list) and 3 <= len(points) <= 4000)
        point_count += len(points)
        for point in points:
            require(isinstance(point, list) and len(point) == 2
                    and all(finite(value, -10000000, 10000000) for value in point))
    require(point_count <= 20000)


def validate_manifest(entries):
    require(isinstance(entries, list) and len(entries) == 2)
    seen = set()
    for item in entries:
        require(isinstance(item, dict) and set(item) == {'name', 'size_bytes', 'sha256', 'content_type'})
        name = item['name']
        require(isinstance(name, str) and name in ARTIFACT_TYPES and name not in seen)
        seen.add(name)
        require(item['content_type'] == ARTIFACT_TYPES[name])
        require(type(item['size_bytes']) is int and 0 < item['size_bytes'] <= MAX_JSON_BYTES)
        require(isinstance(item['sha256'], str) and HEX64.fullmatch(item['sha256']))


def validate_execution(execution, operation, phase):
    require(isinstance(execution, dict) and execution.get('engine') == 'CODEX_TOOLS'
            and execution.get('toolkit_version') == '1' and execution.get('model') == operation.model)
    calls = execution.get('tool_calls')
    require(isinstance(calls, list) and 2 <= len(calls) <= 12)
    identities, succeeded = set(), []
    for call in calls:
        require(isinstance(call, dict))
        key = call.get('call_id')
        require(isinstance(key, str) and 1 <= len(key) <= 128 and key not in identities)
        identities.add(key)
        require(call.get('tool') in ('inspect_source', 'search_layout', 'finalize_layout'))
        require(call.get('status') in ('SUCCEEDED', 'FAILED', 'TIMEOUT'))
        require(isinstance(call.get('arguments_sha256'), str) and HEX64.fullmatch(call['arguments_sha256']))
        require(finite(call.get('duration_ms'), 0, 1200000))
        if call['status'] == 'SUCCEEDED':
            succeeded.append(call['tool'])
    require(succeeded and succeeded[0] == 'inspect_source'
            and calls[-1]['tool'] == 'finalize_layout' and calls[-1]['status'] == 'SUCCEEDED')
    if phase == 'nest':
        require(type(execution.get('guided_attempts')) is int and 1 <= execution['guided_attempts'] <= 3)
        require('search_layout' in succeeded and sum(call['tool'] == 'search_layout' for call in calls) >= 2)


def validate_result(result, parameters):
    require(isinstance(result, dict) and isinstance(result.get('placements'), list))
    placements = result['placements']
    expected = {piece['piece_id']: piece['quantity'] * parameters['set_count'] for piece in parameters['pieces']}
    require(len(placements) == sum(expected.values()) and len(placements) <= 160)
    for row in placements:
        require(isinstance(row, dict) and isinstance(row.get('piece_id'), str)
                and type(row.get('copy')) is int and 0 <= row['copy'] < 160)
        require(all(finite(row.get(field), -0.000001) for field in ('x', 'y', 'angle')))
    require(Counter(row['piece_id'] for row in placements) == expected)
    require(len({(row['piece_id'], row['copy']) for row in placements}) == len(placements))
    validation = result.get('validation')
    require(isinstance(validation, dict) and all(validation.get(key) is True for key in
            ('passed', 'quantities_valid', 'bounds_valid', 'rotations_valid', 'overlap_free')))
    require(validation.get('piece_count') == len(placements))
    require(all(finite(result.get(field), .000001) for field in ('width_mm', 'length_mm'))
            and finite(result.get('gap_mm')) and finite(result.get('utilization_percent'), 0, 100.000001))
    require(result['width_mm'] == float(parameters['width_mm']) and result['gap_mm'] == float(parameters['gap_mm']))
    require(result.get('set_count') == parameters['set_count']
            and result.get('products_per_set') == parameters['products_per_set']
            and result.get('product_quantity') == parameters['set_count'] * parameters['products_per_set'])
    require(isinstance(result.get('consumption_m'), str) and len(result['consumption_m']) <= 80
            and re.fullmatch(r'\d+(?:\.\d+)?', result['consumption_m']))
    require(isinstance(result.get('consumption_rounded_m'), str)
            and re.fullmatch(r'\d{1,20}\.\d{4}', result['consumption_rounded_m']))
    try:
        require(Decimal(result['consumption_m']) > 0 and Decimal(result['consumption_rounded_m']) > 0)
    except InvalidOperation as exc:
        raise NestingFailure('EXECUTOR_RESULT_INVALID') from exc


def validate_envelope(job, operation, data):
    require(isinstance(data, dict) and set(data) == {'schema_version', 'phase', 'source_sha256',
            'analysis_digest', 'parameters_digest', 'analysis', 'result', 'artifacts', 'execution'})
    phase = {'EXTRACT': 'extract', 'NEST': 'nest'}.get(job.phase)
    require(type(data['schema_version']) is int and data['schema_version'] == 2
            and phase and data['phase'] == phase and data['source_sha256'] == job.sha256)
    require(isinstance(data['analysis_digest'], str) and HEX64.fullmatch(data['analysis_digest']))
    validate_analysis(data['analysis'])
    validate_execution(data['execution'], operation, phase)
    if phase == 'extract':
        require(data['parameters_digest'] == '' and data['result'] is None and data['artifacts'] == [])
    else:
        require(data['analysis_digest'] == job.analysis_digest
                and data['parameters_digest'] == canonical_digest(job.parameters))
        validate_manifest(data['artifacts'])
        validate_result(data['result'], job.parameters)

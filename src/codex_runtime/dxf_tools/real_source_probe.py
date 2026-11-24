"""显式运行的真实 DXF 工具技术探针；没有模型调用，不能当作模型验收。"""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import tempfile

from .session import DxfToolSession


async def main():
    root = Path('/tmp/haiqu-dxf-executor-20261105-tests')
    root.mkdir(mode=0o700)
    previous = tempfile.tempdir
    tempfile.tempdir = str(root)
    try:
        raw = Path('/input/source.dxf').read_bytes()
        case = json.loads(Path('/input/geometry-case.json').read_text())
        payload = {'schema_version': 2, 'phase': 'extract', 'source': {
            'data_base64': base64.b64encode(raw).decode(), 'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'unit': 'mm'}}
        async with DxfToolSession(payload) as session:
            inspected = await session.call('inspect_source', {}, 'probe-extract-inspect')
            await session.call('finalize_layout', {}, 'probe-extract-finalize')
            extracted, _ = session.completed_result()
        print(json.dumps({'stage': 'extracted', 'model_called': False,
                          'pieces': len(extracted['analysis']['pieces'])}), flush=True)
        payload.update(phase='nest', parameters=case['parameters'], analysis_digest=inspected['analysis_digest'])
        async with DxfToolSession(payload) as session:
            await session.call('inspect_source', {}, 'probe-nest-inspect')
            baseline = await session.call('search_layout', {'mode': 'baseline', 'proposal': None}, 'probe-baseline')
            context = baseline['search_context']
            print(json.dumps({'stage': 'baseline', 'length_mm': baseline['best_length_mm'],
                              'consumption_m': baseline['consumption_m']}), flush=True)
            pieces = {row['piece_id']: row for row in context['pieces']}
            instances = context['instances']
            orders = [sorted(instances, key=lambda row: -pieces[row['piece_id']]['area_mm2']),
                      list(reversed(instances)),
                      sorted(instances, key=lambda row: (-pieces[row['piece_id']]['width_mm'], row['copy']))]
            proposal = {'schema_version': 1, 'constraint_fingerprint': context['constraint_fingerprint'],
                'plans': [{'reason': '技术探针预置计划，非模型生成', 'order': [
                    {'instance_id': row['instance_id'], 'angles': pieces[row['piece_id']]['allowed_angles']}
                    for row in order]} for order in orders]}
            await session.call('search_layout', {'mode': 'guided', 'proposal': proposal}, 'probe-guided')
            await session.call('finalize_layout', {}, 'probe-nest-finalize')
            data, artifacts = session.completed_result()
            print(json.dumps({'stage': 'finalized', 'model_called': False,
                'source_sha256': data['source_sha256'], 'analysis_digest': data['analysis_digest'],
                'parameters_digest': data['parameters_digest'], 'pieces': len(data['result']['placements']),
                'length_mm': data['result']['length_mm'], 'consumption_m': data['result']['consumption_m'],
                'consumption_rounded_m': data['result']['consumption_rounded_m'],
                'validation': data['result']['validation'], 'optimization': data['result'].get('optimization'),
                'artifacts': data['artifacts'], 'tool_calls': data['execution']['tool_calls'],
                'artifact_bytes_read': sum(map(len, artifacts.values()))}), flush=True)
    finally:
        tempfile.tempdir = previous
        root.rmdir()
    print(json.dumps({'stage': 'cleaned', 'temporary_root_exists': root.exists()}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())

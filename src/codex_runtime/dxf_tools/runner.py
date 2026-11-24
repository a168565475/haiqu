"""一个工具调用一个有界子进程；不初始化 Django，不接收模型代码。"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import traceback


MAX_BYTES = 8 * 1024 * 1024


def render_outputs(analysis, result):
    from codex_runtime.dxf_tools.dxf_geometry import DxfError
    from codex_runtime.dxf_tools.dxf_rendering import export_dxf, render_svg
    # 逐件生成和检查，SVG 超限时不继续分配 DXF。
    for name, render in [('layout.svg', lambda: render_svg(analysis, result).encode('utf-8')),
                         ('layout.dxf', lambda: export_dxf(analysis, result))]:
        content = render()
        if not 0 < len(content) <= MAX_BYTES:
            raise DxfError('RESULT_LIMIT', '排料导出超过限制。')
        yield name, content


def main():
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (175, 175))
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from codex_runtime.dxf_tools.dxf_geometry import DxfError, analyze_dxf
    from codex_runtime.dxf_tools.dxf_nesting import _parameters, nest_pieces
    from codex_runtime.dxf_tools.dxf_codex_optimization import (
        _checked_baseline, _outline, make_codex_payload, refine_with_codex)
    from codex_runtime.dxf_tools.session import digest
    from shapely.geometry import Polygon

    def fail(code, message):
        raise DxfError(code, message)

    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        fail('RESULT_LIMIT', '工具输入超过限制。')
    payload = json.loads(raw)
    source = Path(payload['source_path'])
    try:
        info = source.lstat()
    except FileNotFoundError:
        fail('SOURCE_MISSING', '源文件不存在。')
    if source.resolve() != source or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail('SOURCE_CHANGED', '源文件已变化。')
    with source.open('rb') as stream:
        data = stream.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != payload['sha256']:
        fail('SOURCE_CHANGED', '源文件已变化。')
    operation = payload['operation']
    if operation == 'inspect':
        analysis = analyze_dxf(data, source_unit=payload['source_unit'])
        analysis_digest = digest(analysis)
        if payload['phase'] == 'nest':
            if analysis_digest != payload['analysis_digest']:
                fail('SOURCE_CHANGED', '提取摘要变化，请重新上传并确认裁片。')
            _parameters(analysis, payload['parameters'])
        budget = max(8, min(96, 2500 // len(analysis['pieces'])))
        summary = {**analysis, 'pieces': [{**piece, 'points': _outline(Polygon(piece['points']), budget)}
                                        for piece in analysis['pieces']]}
        response = {'analysis': analysis, 'summary': summary, 'analysis_digest': analysis_digest}
    elif operation == 'baseline':
        result = nest_pieces(payload['analysis'], payload['parameters'], timeout_seconds=payload['budget'])
        response = {'result': result, 'search_context': make_codex_payload(payload['analysis'], payload['parameters'], result)}
    elif operation == 'guided':
        result = refine_with_codex(payload['analysis'], payload['parameters'], payload['baseline'],
                                   payload['proposal'], timeout_seconds=payload['budget'])
        response = {'result': result, 'search_context': make_codex_payload(payload['analysis'], payload['parameters'], result)}
    elif operation == 'finalize':
        if payload['phase'] == 'extract':
            response = {'result': None}
        else:
            _, result = _checked_baseline(payload['analysis'], payload['parameters'], payload['baseline'])
            for name, content in render_outputs(payload['analysis'], result):
                path = source.parent / name
                with path.open('xb') as output:
                    output.write(content)
                path.chmod(0o400)
            response = {'result': result}
    else:
        raise ValueError('Unknown tool operation')
    output = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(output) > MAX_BYTES:
        fail('RESULT_LIMIT', '工具结果超过限制。')
    sys.stdout.buffer.write(output)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        geometry = sys.modules.get('codex_runtime.dxf_tools.dxf_geometry')
        error_class = getattr(geometry, 'DxfError', None)
        if error_class is not None and isinstance(error, error_class):
            print(json.dumps({'error_code': error.code}))
            sys.exit(2)
        # 保留内部错误类型和代码位置，不把异常消息中的源图文字或坐标写入公共日志。
        print(json.dumps({'exception_type': type(error).__name__, 'frames': [
            f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
            for frame in traceback.extract_tb(error.__traceback__)[-10:]]}), file=sys.stderr)
        sys.exit(1)

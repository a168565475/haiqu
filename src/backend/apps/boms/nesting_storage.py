"""排料源文件只保存在私有目录；路径由服务端 UUID 和固定文件名组成。"""
import hashlib
import logging
import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

from apps.imports.security import InfectedFile, ScannerUnavailable, scan_upload


MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
logger = logging.getLogger(__name__)

ERROR_MESSAGES = {
    "CODEX_INVALID_PROPOSAL": "Codex 执行端未能完成符合当前裁片约束的排料，请重试。",
    "EXECUTOR_RESULT_INVALID": "执行端结果与当前文件或参数不一致，禁止采用。",
    "ARTIFACT_INVALID": "执行端成果文件不完整或摘要不一致，请重新执行。",
    "UNSUPPORTED_CAPABILITY": "现有 Codex 连接服务尚不支持 DXF 执行工具，请先更新执行端。",
    "NOT_READY": "现有 Codex 连接尚未就绪，请检查连接设置后重试。",
    "UPSTREAM_UNAVAILABLE": "无法访问现有 Codex 执行端，请检查连接后重试。",
    "AUTH_REQUIRED": "现有 Codex 连接需要重新登录。",
    "USAGE_LIMIT_EXCEEDED": "Codex 当前额度不足，任务未完成。",
    "MODEL_UNAVAILABLE": "现有连接所选模型暂不可用。",
    "TIMEOUT": "Codex 执行等待超时，本次没有可采用的结果。",
    "INVALID_RESPONSE": "Codex 执行端返回了无效结果，禁止采用。",
    "TOOL_SEQUENCE": "Codex 尚未完成规定的读取、排料和校验工具流程，请重试。",
    "TOOL_LIMIT": "本次 Codex 排料达到工具调用上限，未生成可采用成果。",
    "DXF_INVALID": "DXF 文件无法解析，请检查文件格式。",
    "DXF_BINARY": "当前仅支持文本 DXF，请另存为文本 DXF。",
    "DXF_TOO_LARGE": "DXF 文件超过大小限制。",
    "DXF_UNIT_UNKNOWN": "DXF 单位不明确，请选择原图单位后重新上传。",
    "DXF_UNSUPPORTED": "DXF 包含暂不支持的几何对象，请检查裁片轮廓。",
    "DXF_COMPLEXITY": "图纸或混排几何过于复杂，请简化图纸或减少混排套数。",
    "DXF_OPEN_CONTOUR": "检测到未闭合或分叉的轮廓，请在制图软件中修正。",
    "DXF_INVALID_CONTOUR": "检测到无效或自交轮廓，请修正后重新上传。",
    "DXF_AMBIGUOUS_CONTOUR": "轮廓存在歧义，无法安全识别为独立裁片。",
    "DXF_NO_PIECES": "DXF 中没有找到可用的闭合裁片。",
    "NEST_PARAMETERS": "排料参数不完整或不符合当前裁片。",
    "NEST_TOO_MANY_PIECES": "排料总片数不能超过 160 片。",
    "NEST_TOO_WIDE": "至少一种裁片在允许方向下超出净门幅。",
    "NEST_TIMEOUT": "计算超时，尚未得到完整可用的排料结果。",
    "NEST_VALIDATION": "排料结果未通过完整性或不重叠检查。",
    "SOURCE_MISSING": "原 DXF 文件不存在或无法安全读取。",
    "SOURCE_CHANGED": "原 DXF 文件已发生变化，请重新上传。",
    "SCAN_INFECTED": "文件未通过病毒扫描，请检查后重新上传。",
    "SCAN_UNAVAILABLE": "病毒扫描服务暂时不可用，请稍后重试。",
    "STORAGE_UNSAFE": "排料私有目录配置无效，请联系管理员。",
    "STORAGE_UNAVAILABLE": "排料成果文件暂时无法保存，请联系管理员检查存储后重试。",
    "PERMISSION_REVOKED": "任务发起人的权限或目标面料已变化，请重新检查。",
    "INTERRUPTED": "排料进程已中断，请重新计算或上传。",
    "RESULT_LIMIT": "排料输出超过安全大小限制，请简化原图。",
    "INTERNAL_ERROR": "排料处理发生内部错误，请联系管理员查看日志。",
}


class NestingFailure(APIException):
    status_code = 422

    def __init__(self, code):
        self.code = code if code in ERROR_MESSAGES else "INTERNAL_ERROR"
        self.api_error_code = self.code
        if self.code == "SCAN_UNAVAILABLE":
            self.status_code = 503
        super().__init__(ERROR_MESSAGES[self.code], code=self.code)


def directory(job_id, *, create=False):
    root = Path(settings.BOM_NESTING_ROOT).absolute()
    if root.resolve() != root:
        raise NestingFailure("STORAGE_UNSAFE")
    target = root / str(UUID(str(job_id)))
    if target.resolve() != target or (target.exists() and not target.is_dir()):
        raise NestingFailure("STORAGE_UNSAFE")
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.mkdir(mode=0o700)
    return target


def read_upload(upload):
    name = Path(str(upload.name or "").replace("\\", "/")).name
    if len(name) > 255 or Path(name).suffix.lower() != ".dxf":
        raise ValidationError({"file": "仅支持 DXF 文件。"})
    if not 0 < upload.size <= MAX_SOURCE_BYTES:
        raise ValidationError({"file": "DXF 文件必须大于 0 字节且不超过 5 MiB。"})
    data = bytearray()
    for chunk in upload.chunks():
        if len(data) + len(chunk) > MAX_SOURCE_BYTES:
            raise ValidationError({"file": "DXF 文件不能超过 5 MiB。"})
        data.extend(chunk)
    if not data or data.startswith(b"AutoCAD Binary DXF") or b"\x00" in data:
        raise ValidationError({"file": "当前仅支持非空的文本 DXF 文件。"})
    return name, bytes(data), hashlib.sha256(data).hexdigest()


def write_source(job, data):
    target = directory(job.pk, create=True)
    try:
        with (target / "source.dxf").open("xb") as output:
            output.write(data)
        os.chmod(target / "source.dxf", 0o600)
        try:
            return scan_upload(target / "source.dxf")[0]
        except InfectedFile as exc:
            raise NestingFailure("SCAN_INFECTED") from exc
        except ScannerUnavailable as exc:
            raise NestingFailure("SCAN_UNAVAILABLE") from exc
    except BaseException:
        remove_new_source(job)
        raise


def remove_new_source(job):
    """只用于本次创建失败的精确目录，不清理历史任务。"""
    target = directory(job.pk)
    if not target.exists():
        return
    files = list(target.iterdir())
    if any(path.name != "source.dxf" or path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 for path in files):
        raise NestingFailure("STORAGE_UNSAFE")
    for path in files:
        path.unlink()
    target.rmdir()


def source_path(job):
    path = directory(job.pk) / "source.dxf"
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise NestingFailure("SOURCE_MISSING")
    if path.stat().st_size != job.size_bytes or not 0 < job.size_bytes <= MAX_SOURCE_BYTES:
        raise NestingFailure("SOURCE_CHANGED")
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != job.sha256:
            raise NestingFailure("SOURCE_CHANGED")
    return path


def write_artifacts(job, manifest, contents):
    from .nesting_executor_contract import validate_manifest
    validate_manifest(manifest)
    if not isinstance(contents, dict) or set(contents) != {entry['name'] for entry in manifest}:
        raise NestingFailure('ARTIFACT_INVALID')
    for entry in manifest:
        value = contents[entry['name']]
        if (not isinstance(value, bytes) or len(value) != entry['size_bytes']
                or hashlib.sha256(value).hexdigest() != entry['sha256']):
            raise NestingFailure('ARTIFACT_INVALID')
    target = directory(job.pk)
    for entry in manifest:
        destination = target / entry['name']
        if destination.is_symlink() or (destination.exists()
                and (not destination.is_file() or destination.stat().st_nlink != 1)):
            raise NestingFailure('STORAGE_UNSAFE')
        temporary = target / ('.artifact-' + str(uuid4()) + '.tmp')
        try:
            try:
                with temporary.open('xb') as output:
                    output.write(contents[entry['name']])
                os.chmod(temporary, 0o600)
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        except OSError as exc:
            logger.exception('DXF artifact storage failed for job %s', job.pk)
            raise NestingFailure('STORAGE_UNAVAILABLE') from exc


def open_artifact(job, name):
    from .nesting_executor_contract import ARTIFACT_TYPES
    if name not in ARTIFACT_TYPES:
        raise NestingFailure('ARTIFACT_INVALID')
    entry = next((item for item in job.artifacts if item.get('name') == name), None)
    path = directory(job.pk) / name
    if not entry or path.is_symlink() or not 0 < entry['size_bytes'] <= MAX_JSON_BYTES:
        raise NestingFailure('ARTIFACT_INVALID')
    stream = None
    try:
        # 校验并返回同一文件句柄，重算时替换同名文件不能改变本次下载内容。
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        stream = os.fdopen(descriptor, 'rb')
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size != entry['size_bytes']:
            raise NestingFailure('ARTIFACT_INVALID')
        if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
            raise NestingFailure('ARTIFACT_INVALID')
        stream.seek(0)
        return stream
    except (OSError, NestingFailure) as exc:
        if stream is not None:
            stream.close()
        if isinstance(exc, NestingFailure):
            raise
        logger.exception('DXF artifact read failed for job %s', job.pk)
        raise NestingFailure('ARTIFACT_INVALID') from exc

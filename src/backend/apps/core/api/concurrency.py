import hashlib

from rest_framework.exceptions import APIException


class PreconditionRequired(APIException):
    status_code = 428
    default_detail = "修改请求必须携带 If-Match。"
    default_code = "precondition_required"


class PreconditionFailed(APIException):
    status_code = 412
    default_detail = "数据已被其他人修改，请刷新后重试。"
    default_code = "precondition_failed"


def etag_for_instance(instance):
    updated_at = getattr(instance, "updated_at", None)
    if updated_at is None:
        raise ValueError("只有带 updated_at 的资源才能生成 ETag。")

    source = f"{instance.pk}:{updated_at.isoformat()}".encode()
    digest = hashlib.sha256(source).hexdigest()
    return f'"{digest}"'


def require_matching_etag(request, instance):
    expected_etag = request.headers.get("If-Match")
    if not expected_etag:
        raise PreconditionRequired()
    if expected_etag != etag_for_instance(instance):
        raise PreconditionFailed()

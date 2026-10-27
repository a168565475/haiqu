"""历史外发流程共用的数量校验、管材换算与请求锁。"""
import hashlib

from django.db import connection

from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import MaterialFlowValueError, decimal_quantity, pipe_issue


def lock_request(kind, request_id):
    """请求号事务锁先于单据锁，跨订单复用也返回业务冲突，不撞唯一键。"""
    key = int.from_bytes(hashlib.sha256(f"outsourcing:{kind}:{request_id}".encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def quantity(value, field="quantity", *, integer=False, allow_zero=False):
    try:
        return decimal_quantity(value, field, places=0 if integer else 4, allow_zero=allow_zero)
    except MaterialFlowValueError as error:
        raise ValidationError({field: str(error), "code": error.code}) from error


def pipe_amount(value, snapshot):
    try:
        return pipe_issue(requested_pieces=value, pieces_per_bar=snapshot["pieces_per_bar"],
                          raw_bar_length_m=snapshot["raw_bar_length_m"])
    except MaterialFlowValueError as error:
        raise ValidationError({"quantity": str(error), "code": error.code}) from error

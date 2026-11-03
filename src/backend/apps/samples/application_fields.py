"""打样申请的岗位字段和手填编号规则。"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.access_control.selectors import current_assignments
from apps.core.auth import active_employee_for
from apps.core.models import uppercase_code_validator
from .models import SampleRequest


def is_sample_salesperson(request):
    actor = active_employee_for(request.user) if request else None
    return bool(actor and current_assignments(actor).filter(role_profile__role_code='SALESPERSON').exists())


def normalize_manual_request_number(value):
    number = value.strip().upper()
    if not number or number.startswith('HTS'):
        raise ValidationError('请填写打样单号后缀，不要填写 HTS 前缀。')
    try:
        uppercase_code_validator(number)
        uppercase_code_validator(f'HTS{number}')
    except DjangoValidationError as error:
        raise ValidationError(error.messages) from error
    return number


def request_number_values(number, sample=None):
    """历史编号未改时保持原样，沿用数据库现有唯一约束。"""
    number = normalize_manual_request_number(number)
    if sample is not None and number == sample.manual_request_number:
        return {'manual_request_number': number, 'request_number': sample.request_number}
    generated = f'HTS{number}'
    matches = SampleRequest.objects.filter(Q(manual_request_number=number) | Q(request_number=generated))
    if sample is not None:
        matches = matches.exclude(pk=sample.pk)
    if matches.exists():
        raise ValidationError({'manual_request_number': '该打样单号已存在。'})
    return {'manual_request_number': number, 'request_number': generated}

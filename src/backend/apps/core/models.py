import uuid

from django.contrib.postgres.fields import DateTimeRangeField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Func, Q
from django.db.models.functions import Upper


uppercase_code_validator = RegexValidator(
    regex=r"^[A-Z0-9][A-Z0-9._-]*$",
    message="编码只能包含大写字母、数字、点、下划线和连字符。",
)

country_code_validator = RegexValidator(
    regex=r"^[A-Z]{2}$",
    message="国家代码必须是两位大写字母。",
)

currency_code_validator = RegexValidator(
    regex=r"^[A-Z]{3}$",
    message="币种代码必须是三位大写字母。",
)


def uppercase_code_condition(field_name: str) -> Q:
    """生成数据库级大写编码检查条件。"""

    return Q(**{field_name: Upper(F(field_name))})


class DateTimeRange(Func):
    """供 PostgreSQL 排斥约束使用的 [开始时间, 结束时间) 区间。"""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class UUIDPrimaryKeyModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDPrimaryKeyModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ArchivableModel(TimeStampedModel):
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    archive_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.archived_at is None and (self.archived_by_employee_id is not None or self.archive_reason):
            raise ValidationError("未归档记录不能填写归档人或归档原因。")

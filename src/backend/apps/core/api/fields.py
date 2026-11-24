import re

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


@extend_schema_field({"type": "string", "pattern": MONTH_PATTERN})
class CalendarMonthField(serializers.DateField):
    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m", input_formats=("%Y-%m",), **kwargs)

    def to_internal_value(self, value):
        if isinstance(value, str) and not re.fullmatch(MONTH_PATTERN, value):
            self.fail("invalid", format="YYYY-MM")
        return super().to_internal_value(value)

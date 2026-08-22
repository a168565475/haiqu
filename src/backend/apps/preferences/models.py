from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel, uppercase_code_validator


class SavedView(ArchivableModel):
    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="saved_views",
    )
    module_code = models.CharField(max_length=80, validators=[uppercase_code_validator])
    view_name = models.CharField(max_length=150)
    filter_definition = models.JSONField(default=dict)
    column_definition = models.JSONField(default=list, blank=True)
    sort_definition = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "saved_view"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "module_code", "view_name"],
                condition=Q(archived_at__isnull=True),
                name="saved_view_active_name_uniq",
            ),
            models.UniqueConstraint(
                fields=["employee", "module_code"],
                condition=Q(is_default=True, archived_at__isnull=True),
                name="saved_view_one_default_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "module_code", "sort_order", "id"],
                condition=Q(archived_at__isnull=True),
                name="saved_view_employee_module_idx",
            ),
        ]


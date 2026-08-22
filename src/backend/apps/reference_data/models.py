from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel, uppercase_code_condition, uppercase_code_validator


class DictionaryStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "启用"
    INACTIVE = "INACTIVE", "停用"


class ReferenceDictionary(ArchivableModel):
    """只存放简单可配置选项，不承载货币、税率、产品等正式主数据。"""

    category_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    item_code = models.CharField(max_length=50, validators=[uppercase_code_validator])
    display_name = models.CharField(max_length=150)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20,
        choices=DictionaryStatus.choices,
        default=DictionaryStatus.ACTIVE,
    )
    sort_order = models.PositiveIntegerField(default=0)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "reference_dictionary"
        ordering = ["category_code", "sort_order", "item_code"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=DictionaryStatus.values), name="ref_dict_status_valid"),
            models.CheckConstraint(
                condition=uppercase_code_condition("category_code"),
                name="ref_dict_category_uppercase",
            ),
            models.CheckConstraint(
                condition=uppercase_code_condition("item_code"),
                name="ref_dict_item_uppercase",
            ),
            models.UniqueConstraint(
                fields=["category_code", "item_code"],
                name="ref_dict_category_item_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["category_code", "status", "sort_order", "id"],
                condition=Q(archived_at__isnull=True),
                name="ref_dict_active_list_idx",
            ),
        ]

    def __str__(self):
        return f"{self.category_code}.{self.item_code} - {self.display_name}"

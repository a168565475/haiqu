from django.db import models

from apps.core.models import TimeStampedModel


class ReasoningEffort(models.TextChoices):
    AUTO = "auto", "自动"
    LOW = "low", "低"
    MEDIUM = "medium", "中"
    HIGH = "high", "高"
    XHIGH = "xhigh", "超高"
    MAX = "max", "最高"


class OpenAIKeyConfig(TimeStampedModel):
    """按员工隔离的 OpenAI 配置；完整 Key 只保存为密文。"""

    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="openai_key_configs",
    )
    label = models.CharField(max_length=100)
    provider = models.CharField(max_length=50, default="openai")
    model = models.CharField(max_length=100, default="gpt-6-astra")
    document_reasoning_effort = models.CharField(max_length=8, choices=ReasoningEffort.choices, default=ReasoningEffort.AUTO)
    material_reasoning_effort = models.CharField(max_length=8, choices=ReasoningEffort.choices, default=ReasoningEffort.AUTO)
    base_url = models.URLField(max_length=500, blank=True, default="")
    key_ciphertext = models.TextField()
    key_last4 = models.CharField(max_length=4)
    key_fingerprint = models.CharField(max_length=64)

    class Meta:
        db_table = "ai_openai_key_config"
        ordering = ["label", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "label"],
                name="ai_openai_key_employee_label_uniq",
            ),
        ]
        indexes = [models.Index(fields=["employee", "label"], name="ai_openai_key_employee_idx")]

    def __str__(self):
        return f"{self.employee_id} - {self.label}"


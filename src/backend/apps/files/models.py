from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel


class FileScanStatus(models.TextChoices):
    PENDING = "PENDING", "待扫描"
    CLEAN = "CLEAN", "安全"
    INFECTED = "INFECTED", "风险文件"
    FAILED = "FAILED", "扫描失败"


class BusinessFile(ArchivableModel):
    uploaded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_business_files",
    )
    original_name = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=500, unique=True)
    content_type = models.CharField(max_length=150)
    size_bytes = models.PositiveBigIntegerField()
    content_hash = models.CharField(max_length=128, blank=True)
    scan_status = models.CharField(
        max_length=20,
        choices=FileScanStatus.choices,
        default=FileScanStatus.PENDING,
    )
    scanned_at = models.DateTimeField(null=True, blank=True)
    scan_message = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "business_file"
        constraints = [
            models.CheckConstraint(condition=Q(scan_status__in=FileScanStatus.values), name="business_file_scan_status_valid"),
        ]
        indexes = [
            models.Index(
                fields=["content_hash"],
                condition=~Q(content_hash=""),
                name="business_file_hash_idx",
            ),
            models.Index(
                fields=["scan_status", "created_at", "id"],
                condition=Q(scan_status=FileScanStatus.PENDING),
                name="business_file_scan_queue_idx",
            ),
        ]

    def __str__(self):
        return self.original_name

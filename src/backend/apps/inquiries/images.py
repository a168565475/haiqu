from apps.files.models import BusinessFile, USABLE_FILE_SCAN_STATUSES
from .selectors import accessible_inquiries


def inquiry_reference_images(inquiry_id, request):
    """报价和样品复用询盘图片时执行相同的数据范围和扫描检查。"""
    if not request.user.has_perm('inquiries.view_inquiryfilelink'):
        return BusinessFile.objects.none()
    if not accessible_inquiries(request, 'view_inquiry').filter(pk=inquiry_id, archived_at__isnull=True).exists():
        return BusinessFile.objects.none()
    return BusinessFile.objects.filter(
        inquiry_links__inquiry_id=inquiry_id, archived_at__isnull=True,
        scan_status__in=USABLE_FILE_SCAN_STATUSES, content_type__in=['image/jpeg', 'image/png'],
    ).exclude(inquiry_links__file_role='COMMUNICATION_IMAGE').order_by('created_at', 'id').distinct()

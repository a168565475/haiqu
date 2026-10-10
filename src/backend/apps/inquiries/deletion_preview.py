from apps.customers.hard_delete import _scope_for_inquiry


def inquiry_deletion_preview(inquiry):
    """只读复用现有删除范围；统计关联对象，不宣称穷尽外键递归删除数量。"""
    scope = _scope_for_inquiry(inquiry)
    return {
        "inquiry_number": inquiry.inquiry_number,
        "quotation_count": len(scope.quotation_ids),
        "sample_count": len(scope.sample_ids),
        "task_count": len(scope.task_ids),
        "inquiry_file_link_count": inquiry.file_links.count(),
    }

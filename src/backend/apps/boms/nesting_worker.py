"""ERP 工作进程只提交/跟踪 Codex 任务，不读取几何、不运行排料子进程。"""
import logging

from django.utils import timezone

from .nesting_storage import ERROR_MESSAGES


logger = logging.getLogger(__name__)


def fail(job, code):
    job.error_code = code if code in ERROR_MESSAGES else "INTERNAL_ERROR"
    job.error_message = ERROR_MESSAGES[job.error_code]
    job.status, job.result, job.finished_at = "FAILED", {}, timezone.now()
    job.execution, job.artifacts, job.optimization = {}, [], {}
    job.save()


def process_once():
    from .nesting_codex import enqueue_next
    return enqueue_next()

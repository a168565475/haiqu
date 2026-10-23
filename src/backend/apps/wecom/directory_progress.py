"""通讯录请求的短期进度；仅记录计数，不保存成员资料，也不改变原事务。"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from django.core.cache import caches
from redis.exceptions import RedisError
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.api.exceptions import Conflict


logger = logging.getLogger(__name__)
current = ContextVar("directory_progress", default=None)
TTL = 900


def cache_key(user_id, progress_id):
    return f"directory-progress:{user_id}:{progress_id}"


class Progress:
    def __init__(self, key, total):
        self.key = key
        self.data = {"status": "RUNNING", "completed": 0, "total": total, "phase": "正在核对来源"}

    def write(self):
        # 进度缓存故障不应使已提交的员工数据被报告为保存失败。
        try:
            caches["wecom"].set(self.key, self.data, TTL)
        except (RedisError, OSError):
            logger.exception("通讯录进度缓存写入失败")


@contextmanager
def track(request, total):
    raw_id = request.headers.get("X-Directory-Progress")
    if not raw_id:
        yield
        return
    try:
        progress_id = UUID(raw_id)
    except (ValueError, AttributeError) as exc:
        raise ValidationError("进度标识必须是有效 UUID。") from exc
    progress = Progress(cache_key(request.user.pk, progress_id), total)
    try:
        created = caches["wecom"].add(progress.key, progress.data, TTL)
    except (RedisError, OSError):
        logger.exception("通讯录进度缓存初始化失败")
        created = True
    if not created:
        raise Conflict("此进度标识已使用，请重新发起请求。")
    token = current.set(progress)
    try:
        yield
    except Exception:
        progress.data["status"] = "FAILED"
        progress.data["phase"] = "操作未完成"
        progress.write()
        raise
    else:
        progress.data.update(status="SUCCESS", completed=progress.data["total"], phase="已完成")
        progress.write()
    finally:
        current.reset(token)


def add_work(count):
    if progress := current.get():
        progress.data["total"] += count
        progress.write()


def advance(phase, count=1):
    if progress := current.get():
        # 最后一个单位由请求成功返回时完成，避免事务回滚前显示 100%。
        progress.data["completed"] = min(progress.data["total"] - 1, progress.data["completed"] + count)
        progress.data["phase"] = phase
        progress.write()


def read(request, progress_id):
    data = caches["wecom"].get(cache_key(request.user.pk, progress_id))
    if data is None:
        raise NotFound("进度尚未建立或已过期。")
    return data

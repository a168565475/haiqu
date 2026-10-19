import logging
import re


class WeComAccessLogFilter(logging.Filter):
    """开发访问日志仅保留企微回调路径，避免记录一次性授权码和state。"""

    callback_query = re.compile(r"(/api/auth/wecom/callback/)\?[^\s]*")

    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                self.callback_query.sub(r"\1", item) if isinstance(item, str) else item
                for item in record.args
            )
        if isinstance(record.msg, str):
            record.msg = self.callback_query.sub(r"\1", record.msg)
        return True

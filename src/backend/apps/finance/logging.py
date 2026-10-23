import logging
import re


class FinanceAccessLogFilter(logging.Filter):
    """账户搜索可能包含完整账号，访问日志不保留该接口查询字符串。"""
    query = re.compile(r"(/api/v1/finance/accounts/)\?[^\s\"]*")

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self.query.sub(r"\1", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self.query.sub(r"\1", item) if isinstance(item, str) else item for item in record.args)
        return True

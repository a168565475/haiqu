"""用真实连接验证：建单等待共用流水时，资料锁仍允许其他单据完成外键检查。"""

import threading

from django.db import connections, transaction

from apps.core.models import DailyBusinessNumberCounter
from apps.core.numbering import next_business_number


def assert_reference_locks_allow_number_holder(test, create, references):
    waiting_for_number = threading.Event()
    results = []
    table = DailyBusinessNumberCounter._meta.db_table

    def run():
        connections.close_all()

        def observe(execute, sql, params, many, context):
            if table in sql and sql.lstrip().upper().startswith("INSERT"):
                waiting_for_number.set()
            return execute(sql, params, many, context)

        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '15s'")
            with connections["default"].execute_wrapper(observe):
                results.append(create())
        except Exception as error:
            results.append(f"UNEXPECTED {type(error).__name__}: {error}")
        finally:
            connections.close_all()

    worker = threading.Thread(target=run)
    try:
        with transaction.atomic():
            earlier = next_business_number("OUTSOURCING_ORDER")
            worker.start()
            test.assertTrue(waiting_for_number.wait(6), results)
            connection = connections["default"]
            quote = connection.ops.quote_name
            # FK 使用 KEY SHARE。NOWAIT 让旧 FOR UPDATE 反序稳定失败，避免靠死锁超时判断。
            with connection.cursor() as cursor:
                for model, pk in references:
                    cursor.execute(
                        f"SELECT 1 FROM {quote(model._meta.db_table)} "
                        f"WHERE {quote(model._meta.pk.column)} = %s FOR KEY SHARE NOWAIT",
                        [pk],
                    )
                    test.assertEqual(cursor.fetchone(), (1,))
    finally:
        if worker.ident is not None:
            worker.join(timeout=20)
    test.assertFalse(worker.is_alive(), results)
    test.assertEqual(results, [f"{earlier[:8]}{int(earlier[8:]) + 1:03d}"])

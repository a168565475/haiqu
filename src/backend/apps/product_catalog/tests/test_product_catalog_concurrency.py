from queue import Queue
from threading import Barrier, Thread
from types import SimpleNamespace

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from apps.core.api.concurrency import PreconditionFailed, etag_for_instance

from ..models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from ..services import add_color


class ProductCatalogConcurrencyTests(TransactionTestCase):
    def test_two_writers_with_same_etag_commit_only_one_color(self):
        category = ProductCatalogCategory.objects.create(name="并发类别")
        name = ProductCatalogName.objects.create(category=category, name="并发完整品名")
        product = ProductCatalog.objects.create(name=name)
        version = etag_for_instance(product)
        ready, outcomes = Barrier(2), Queue()

        def worker(value):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                ready.wait(timeout=10)
                request = SimpleNamespace(headers={"If-Match": version}, META={})
                add_color(product_id=product.pk, value=value, request=request)
                outcomes.put("saved")
            except PreconditionFailed:
                outcomes.put("conflict")
            except Exception as exc:
                outcomes.put(exc)
            finally:
                close_old_connections()

        workers = [Thread(target=worker, args=(color,)) for color in ("红", "蓝")]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in workers), "并发写入线程未结束")
        results = [outcomes.get_nowait() for _ in workers]
        self.assertEqual(sorted(str(result) for result in results), ["conflict", "saved"])
        self.assertEqual(ProductCatalogColor.objects.filter(product=product).count(), 1)

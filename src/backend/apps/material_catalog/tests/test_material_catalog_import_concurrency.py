from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from apps.core.api.concurrency import etag_for_instance
from apps.reference_data.models import ProductionUnit

from .. import importing, services
from ..models import MaterialAllowedUnit, MaterialCatalog


class MaterialCatalogImportConcurrencyTests(TransactionTestCase):
    def test_locked_import_unit_allows_another_catalog_page_unit_to_commit(self):
        unit = ProductionUnit.objects.create(unit_code="IMPORT_CONCURRENT", unit_name="并发导入测试根")
        import_catalog = MaterialCatalog.objects.create(
            category_key="TUBE", template_key="TUBE", name="并发导入主档",
        )
        page_catalog = MaterialCatalog.objects.create(
            category_key="TUBE", template_key="TUBE", name="并发页面主档",
        )
        payload = {
            "version": 1,
            "source": {"filename": "并发导入测试.xlsx", "sha256": "b" * 64},
            "catalogs": [{
                "category_key": "TUBE", "template_key": "TUBE", "name": import_catalog.name,
                "spray_enabled": False, "values": [],
                "units": [{"scope": "BASE", "unit_name": unit.unit_name}],
            }],
        }
        request = SimpleNamespace(headers={"If-Match": etag_for_instance(page_catalog)}, META={})
        import_locked, release_import = Event(), Event()
        import_finished, page_finished, page_committed = Event(), Event(), Event()
        errors = Queue()
        connection_pids = {}
        original_prepare = importing._prepare_catalog

        def pause_with_import_locks(*args, **kwargs):
            result = original_prepare(*args, **kwargs)
            import_locked.set()
            if not release_import.wait(15):
                raise AssertionError("并发测试未及时释放导入事务")
            return result

        def run_worker(name, operation, finished):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '2s'")
                        cursor.execute("SET LOCAL statement_timeout = '6s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        connection_pids[name] = cursor.fetchone()[0]
                    operation()
                # 外键约束可能延迟到提交；必须提交成功后才能发送页面成功信号。
                if name == "page":
                    page_committed.set()
            except Exception as exc:
                errors.put((name, type(exc).__name__, str(exc)))
            finally:
                connections.close_all()
                finished.set()

        importer = Thread(
            target=run_worker,
            args=("import", lambda: importing.import_catalog_payload(payload, apply=True), import_finished),
            name="material-catalog-import-lock", daemon=True,
        )
        page = Thread(
            target=run_worker,
            args=("page", lambda: services.add_unit(
                catalog_id=page_catalog.pk, data={"scope": "BASE", "unit_id": unit.pk}, request=request,
            ), page_finished),
            name="material-catalog-page-unit", daemon=True,
        )
        started = []
        with patch.object(importing, "_prepare_catalog", side_effect=pause_with_import_locks):
            try:
                importer.start()
                started.append(importer)
                self.assertTrue(import_locked.wait(10), "导入线程没有取得主档和单位锁")
                page.start()
                started.append(page)
                self.assertTrue(page_finished.wait(8), "另一档案的页面单位写入没有在限定时间内结束")
                self.assertTrue(page_committed.is_set(), f"导入持锁期间页面提交失败：{list(errors.queue)}")
                self.assertFalse(release_import.is_set())
                self.assertFalse(import_finished.is_set())
                self.assertNotEqual(connection_pids["import"], connection_pids["page"])
                self.assertTrue(MaterialAllowedUnit.objects.filter(catalog=page_catalog, unit=unit).exists())
            finally:
                release_import.set()
                for worker in started:
                    worker.join(timeout=10)
                self.assertFalse(any(worker.is_alive() for worker in started), "并发测试线程未结束")
        self.assertTrue(errors.empty(), list(errors.queue))
        self.assertTrue(MaterialAllowedUnit.objects.filter(catalog=import_catalog, unit=unit).exists())

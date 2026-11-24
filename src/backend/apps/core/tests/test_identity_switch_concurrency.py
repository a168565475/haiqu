"""PostgreSQL races over real HTTP/session requests, without mocked locks.

The lead owns execution and the exclusive test database.  Event/Barrier waits,
future waits and PostgreSQL statements are bounded; each worker owns and closes
its own Django database connection.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from unittest.mock import patch

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core import views as auth_views
from apps.preferences.api.views import SavedViewViewSet
from apps.samples.api.views import SampleRequestViewSet

from .test_identity_switch_api import FLOW_SETTINGS, IdentitySwitchFixtures, copy_browser


WAIT = 15
FUTURE_WAIT = 35


@override_settings(**FLOW_SETTINGS)
class IdentitySwitchConcurrencyTests(IdentitySwitchFixtures, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql", "Identity races must run against real PostgreSQL")
        self.create_identities()
        self.lock_calls = []
        self.worker_pids = []
        self.observations_lock = Lock()
        self.addCleanup(connections.close_all)

    def worker(self, operation, *, barrier=None, lock_attempt=None):
        """Run one request on a real independent, bounded PostgreSQL connection."""
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '20000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]
            with self.observations_lock:
                self.worker_pids.append(pid)

            def observe(execute, sql, params, many, context):
                if "pg_advisory_lock(" in sql.lower() or "pg_advisory_lock_shared(" in sql.lower():
                    with self.observations_lock:
                        self.lock_calls.append((pid, sql, tuple(params or ())))
                    if lock_attempt is not None:
                        lock_attempt.set()
                # Observe the real SQL; do not replace/adapt the locking call.
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe):
                if barrier is not None:
                    barrier.wait(timeout=WAIT)
                return operation()
        finally:
            connections.close_all()

    def assert_real_serialization(self):
        self.assertGreaterEqual(len(self.lock_calls), 2)
        self.assertGreaterEqual(len(set(self.worker_pids)), 2)
        # All requests in this race must lock the same chain, not merely use
        # unrelated advisory locks on separate connections.
        self.assertEqual(len({params for _, _, params in self.lock_calls}), 1)

    def assert_no_identity_cookies(self, response):
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertNotIn(self.return_cookie_name, response.cookies)

    def apply_identity_cookies(self, response, browser):
        """Model a delayed response arriving after a newer browser response."""
        for name in (settings.SESSION_COOKIE_NAME, self.return_cookie_name):
            if name in response.cookies:
                browser.cookies[name] = response.cookies[name].value

    def grant_samples(self, employee):
        from django.contrib.auth.models import Permission
        from apps.samples.models import SampleRequest

        employee.user.user_permissions.add(Permission.objects.get(
            content_type__app_label="samples", codename="view_samplerequest",
        ))
        return SampleRequest.objects.create(
            owner_employee=employee, requested_by_employee=employee,
            request_number=f"LOCK-{employee.employee_code}", requested_at=timezone.now(),
        )

    def test_sample_reads_overlap_under_shared_chain_lock(self):
        sample = self.grant_samples(self.employee)
        self.enter_flow()
        version = self.version()
        browsers = [copy_browser(self.client), copy_browser(self.client)]
        paths = ["/api/v1/sample-requests/", "/api/v1/sample-requests/options/?scope=filters"]
        both_entered = Event()
        release = Event()
        entered = []
        original = SampleRequestViewSet.get_queryset

        def paused(view):
            with self.observations_lock:
                entered.append((view.request.user.pk, view.actor_employee().pk))
                if len(entered) == 2:
                    both_entered.set()
            if not release.wait(timeout=WAIT):
                raise AssertionError("Concurrent sample readers did not both enter")
            return original(view)

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(SampleRequestViewSet, "get_queryset", paused):
                futures = [pool.submit(self.worker, lambda browser=browser, path=path: browser.get(
                    path, HTTP_X_IDENTITY_VERSION=version)) for browser, path in zip(browsers, paths)]
                self.assertTrue(both_entered.wait(timeout=WAIT), "Shared readers were serialized")
                release.set()
                responses = [future.result(timeout=FUTURE_WAIT) for future in futures]
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual([row["id"] for row in responses[0].data["data"]], [str(sample.pk)])
        self.assertEqual(entered, [(self.employee.user_id, self.employee.pk)] * 2)
        self.assert_real_serialization()
        self.assertTrue(all("pg_advisory_lock_shared(" in sql for _, sql, _ in self.lock_calls))
        for response in responses:
            self.assert_no_authentication_cookies(response)

    def assert_sample_readers_block_transition(self, *, returning):
        self.grant_samples(self.employee)
        self.grant_samples(self.other_employee)
        self.enter_flow()
        version = self.version()
        browsers = [copy_browser(self.client), copy_browser(self.client)]
        writer = copy_browser(self.client)
        paths = ["/api/v1/sample-requests/", "/api/v1/sample-requests/options/?scope=filters"]
        both_entered = Event()
        releases = [Event(), Event()]
        writer_attempt = Event()
        entered = []
        original = SampleRequestViewSet.get_queryset

        def paused(view):
            index = 0 if view.action == "list" else 1
            with self.observations_lock:
                entered.append(index)
                if len(entered) == 2:
                    both_entered.set()
            if not releases[index].wait(timeout=WAIT):
                raise AssertionError("Timed out releasing shared sample read")
            return original(view)

        transition_path = "/api/auth/return-admin/" if returning else "/api/auth/switch/"
        payload = {} if returning else {"employee_id": str(self.other_employee.pk)}
        pool = ThreadPoolExecutor(max_workers=3)
        try:
            with patch.object(SampleRequestViewSet, "get_queryset", paused):
                readers = [pool.submit(self.worker, lambda browser=browser, path=path: browser.get(
                    path, HTTP_X_IDENTITY_VERSION=version)) for browser, path in zip(browsers, paths)]
                self.assertTrue(both_entered.wait(timeout=WAIT))
                transition = pool.submit(self.worker, lambda: self.post_json(
                    transition_path, payload, version=version, client=writer), lock_attempt=writer_attempt)
                self.assertTrue(writer_attempt.wait(timeout=WAIT))
                self.assertFalse(transition.done())
                releases[0].set()
                first = readers[0].result(timeout=FUTURE_WAIT)
                self.assertFalse(transition.done(), "Writer passed the remaining shared reader")
                releases[1].set()
                second = readers[1].result(timeout=FUTURE_WAIT)
                changed = transition.result(timeout=FUTURE_WAIT)
        finally:
            for release in releases:
                release.set()
            pool.shutdown(wait=True, cancel_futures=True)
        expected_user = self.admin if returning else self.other_employee.user
        new_version = self.assert_switch_state(changed, active=not returning, can_return=not returning, user=expected_user)
        for response in (first, second):
            self.assertEqual(response.status_code, 200, response.content)
            self.assert_no_authentication_cookies(response)
            self.apply_all_response_cookies(response, writer)
        self.assertEqual(self.version(writer), new_version)
        self.assertEqual(writer.get("/api/auth/me/").data["user"]["id"], expected_user.pk)
        self.assertEqual(browsers[0].get(paths[0], HTTP_X_IDENTITY_VERSION=version).status_code, 409)
        self.assert_real_serialization()
        self.assertEqual(sum("pg_advisory_lock_shared(" in sql for _, sql, _ in self.lock_calls), 2)
        self.assertEqual(sum("pg_advisory_lock(" in sql for _, sql, _ in self.lock_calls), 1)

    def test_switch_waits_for_all_sample_readers_and_late_responses_keep_new_identity(self):
        self.assert_sample_readers_block_transition(returning=False)

    def test_return_waits_for_all_sample_readers_and_late_responses_keep_new_identity(self):
        self.assert_sample_readers_block_transition(returning=True)

    def test_shared_sample_reads_keep_version_checks_and_fall_back_for_session_writes(self):
        self.grant_samples(self.employee)
        self.enter_flow()
        version = self.version()
        paths = ["/api/v1/sample-requests/", "/api/v1/sample-requests/options/?scope=filters"]
        for path in paths:
            for method in (self.client.get, self.client.head):
                with self.subTest(path=path, method=method.__name__):
                    with CaptureQueriesContext(connection) as queries:
                        response = method(path, HTTP_X_IDENTITY_VERSION=version)
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertTrue(any("pg_advisory_lock_shared(" in query["sql"] for query in queries))
                    self.assertTrue(any("pg_advisory_unlock_shared(" in query["sql"] for query in queries))
                    self.assertEqual(method(path).status_code, 428)
                    self.assertEqual(method(path, HTTP_X_IDENTITY_VERSION="stale").status_code, 409)
        for setting in (
            {"SESSION_SAVE_EVERY_REQUEST": True}, {"SECRET_KEY_FALLBACKS": ["old-test-secret"]},
            {"CSRF_USE_SESSIONS": True}, {"SESSION_ENGINE": "django.contrib.sessions.backends.cached_db"},
        ):
            with self.subTest(setting=setting), self.settings(**setting):
                browser = copy_browser(self.client)
                with CaptureQueriesContext(connection) as queries:
                    response = browser.get(paths[0], HTTP_X_IDENTITY_VERSION=version)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(any("pg_advisory_lock(" in query["sql"] for query in queries))
                self.assertFalse(any("pg_advisory_lock_shared(" in query["sql"] for query in queries))
        with CaptureQueriesContext(connection) as queries:
            self.client.get("/api/auth/me/")
        self.assertTrue(any("pg_advisory_lock(" in query["sql"] for query in queries))
        self.assertFalse(any("pg_advisory_lock_shared(" in query["sql"] for query in queries))

    def test_invalidated_parallel_sample_reader_cannot_resave_session_or_block_return(self):
        from apps.organizations.models import Employee

        sample = self.grant_samples(self.employee)
        self.enter_flow()
        version = self.version()
        old_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        reader, invalid_reader, returning_browser = [copy_browser(self.client) for _ in range(3)]
        in_read = Event()
        release = Event()
        return_attempt = Event()
        old_key_saves = []
        original_queryset = SampleRequestViewSet.get_queryset
        original_save = SessionStore.save

        def paused(view):
            in_read.set()
            if not release.wait(timeout=WAIT):
                raise AssertionError("Timed out releasing valid sample reader")
            return original_queryset(view)

        def observed_save(store, *args, **kwargs):
            if store.session_key == old_key:
                old_key_saves.append(old_key)
            return original_save(store, *args, **kwargs)

        pool = ThreadPoolExecutor(max_workers=3)
        try:
            with patch.object(SampleRequestViewSet, "get_queryset", paused), patch.object(SessionStore, "save", observed_save):
                reading = pool.submit(self.worker, lambda: reader.get(
                    "/api/v1/sample-requests/", HTTP_X_IDENTITY_VERSION=version))
                self.assertTrue(in_read.wait(timeout=WAIT))
                Employee.objects.filter(pk=self.employee.pk).update(status="INACTIVE")
                invalid = pool.submit(self.worker, lambda: invalid_reader.get(
                    "/api/v1/sample-requests/", HTTP_X_IDENTITY_VERSION=version)).result(timeout=FUTURE_WAIT)
                self.assertEqual(invalid.status_code, 401, invalid.content)
                self.assert_no_authentication_cookies(invalid)
                self.assertFalse(Session.objects.filter(session_key=old_key).exists())
                returning = pool.submit(self.worker, lambda: self.post_json(
                    "/api/auth/return-admin/", {}, version=version, client=returning_browser), lock_attempt=return_attempt)
                self.assertTrue(return_attempt.wait(timeout=WAIT))
                self.assertFalse(returning.done())
                release.set()
                old_response = reading.result(timeout=FUTURE_WAIT)
                returned = returning.result(timeout=FUTURE_WAIT)
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertEqual(old_response.status_code, 200, old_response.content)
        self.assertEqual([row["id"] for row in old_response.data["data"]], [str(sample.pk)])
        self.assertEqual(old_key_saves, [])
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        new_version = self.assert_switch_state(returned, active=False, can_return=False, user=self.admin)
        self.assert_no_authentication_cookies(old_response)
        self.apply_all_response_cookies(old_response, returning_browser)
        self.assertEqual(self.version(returning_browser), new_version)
        self.assertEqual(reader.get("/api/v1/sample-requests/", HTTP_X_IDENTITY_VERSION=version).status_code, 409)

    def test_original_admin_flush_and_relogin_cannot_be_overwritten_by_late_reader(self):
        from apps.organizations.models import Employee

        admin_employee = Employee.objects.create(user=self.admin, employee_code="LOCK_ADMIN", display_name="锁测试管理员")
        sample = self.grant_samples(admin_employee)
        self.login()
        old_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        reader, invalid_reader, relogin_browser = [copy_browser(self.client) for _ in range(3)]
        in_read = Event()
        release = Event()
        old_key_saves = []
        identities = []
        original_queryset = SampleRequestViewSet.get_queryset
        original_save = SessionStore.save

        def paused(view):
            identities.append(view.request.user.pk)
            in_read.set()
            if not release.wait(timeout=WAIT):
                raise AssertionError("Timed out releasing original administrator read")
            result = original_queryset(view)
            identities.append(view.request.user.pk)
            return result

        def observed_save(store, *args, **kwargs):
            if store.session_key == old_key:
                old_key_saves.append(old_key)
            return original_save(store, *args, **kwargs)

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(SampleRequestViewSet, "get_queryset", paused), patch.object(SessionStore, "save", observed_save):
                reading = pool.submit(self.worker, lambda: reader.get("/api/v1/sample-requests/"))
                self.assertTrue(in_read.wait(timeout=WAIT))
                self.admin.set_password("ChangedIdentityLockPassword123!")
                self.admin.save(update_fields=["password"])
                invalid = pool.submit(self.worker, lambda: invalid_reader.get("/api/v1/sample-requests/")).result(timeout=FUTURE_WAIT)
                self.assertEqual(invalid.status_code, 401, invalid.content)
                self.assertFalse(Session.objects.filter(session_key=old_key).exists())
                relogged = self.login(self.other_employee.user, client=relogin_browser)
                self.assertEqual(relogged.data["user"]["id"], self.other_employee.user_id)
                release.set()
                old_response = reading.result(timeout=FUTURE_WAIT)
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertEqual(old_response.status_code, 200, old_response.content)
        self.assertEqual([row["id"] for row in old_response.data["data"]], [str(sample.pk)])
        self.assertEqual(identities, [self.admin.pk, self.admin.pk])
        self.assertEqual(old_key_saves, [])
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assert_no_authentication_cookies(old_response)
        self.apply_all_response_cookies(old_response, relogin_browser)
        self.assertEqual(relogin_browser.get("/api/auth/me/").data["user"]["id"], self.other_employee.user_id)
        self.assertEqual(reader.get("/api/v1/sample-requests/").status_code, 401)

    def test_shared_sample_500_releases_lock_before_connection_closes(self):
        from apps.core.identity_switch_services import lock_number

        self.grant_samples(self.employee)
        self.enter_flow()
        version = self.version()
        browser = copy_browser(self.client)
        browser.raise_request_exception = False
        returned = Event()
        release = Event()
        number = lock_number(self.root_key)

        def fail_with_open_connection():
            physical = connection.connection
            response = browser.get("/api/v1/sample-requests/", HTTP_X_IDENTITY_VERSION=version)
            self.assertEqual(response.status_code, 500, response.content)
            self.assertIs(connection.connection, physical)
            self.assertFalse(physical.closed)
            returned.set()
            if not release.wait(timeout=WAIT):
                raise AssertionError("Timed out keeping failed shared reader connection open")
            return response

        def probe_exclusive_lock():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [number])
                acquired = cursor.fetchone()[0]
                try:
                    self.assertTrue(acquired, "Failed sample reader leaked its shared lock")
                finally:
                    if acquired:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", [number])
                        self.assertTrue(cursor.fetchone()[0])
            return acquired

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(SampleRequestViewSet, "get_queryset", side_effect=RuntimeError("Intentional sample read failure")):
                failed = pool.submit(self.worker, fail_with_open_connection)
                self.assertTrue(returned.wait(timeout=WAIT))
                self.assertTrue(pool.submit(self.worker, probe_exclusive_lock).result(timeout=FUTURE_WAIT))
                self.assertFalse(failed.done())
                release.set()
                response = failed.result(timeout=FUTURE_WAIT)
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assert_no_authentication_cookies(response)
        self.assertTrue(any("pg_advisory_lock_shared(" in sql for _, sql, _ in self.lock_calls))
        self.assertEqual(self.version(), version)

    def test_two_initial_switches_with_one_version_have_exactly_one_winner(self):
        self.login()
        version = self.version()
        browsers = [copy_browser(self.client), copy_browser(self.client)]
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)
        futures = []
        try:
            for browser, employee in zip(browsers, (self.employee, self.other_employee)):
                futures.append(pool.submit(self.worker, lambda browser=browser, employee=employee: self.post_json(
                    "/api/auth/switch/", {"employee_id": str(employee.pk)}, version=version, client=browser
                ), barrier=barrier))
            responses = [future.result(timeout=FUTURE_WAIT) for future in futures]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertCountEqual([response.status_code for response in responses], [200, 409])
        self.assert_real_serialization()
        winner_index = next(index for index, response in enumerate(responses) if response.status_code == 200)
        loser = responses[1 - winner_index]
        self.assert_no_identity_cookies(loser)
        winner = browsers[winner_index]
        winning_state = responses[winner_index].data["account_switch"]
        self.assertNotEqual(winning_state["identity_version"], version)
        self.assertEqual(winner.get("/api/auth/me/").data["user"]["id"], responses[winner_index].data["user"]["id"])
        self.apply_identity_cookies(loser, winner)
        self.assertEqual(self.version(winner), winning_state["identity_version"])

    def test_two_active_flow_switches_with_one_version_have_exactly_one_winner(self):
        self.enter_flow()
        version = self.version()
        browsers = [copy_browser(self.client), copy_browser(self.client)]
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            futures = [pool.submit(self.worker, lambda browser=browser: self.post_json(
                "/api/auth/switch/", {"employee_id": str(self.other_employee.pk)}, version=version, client=browser
            ), barrier=barrier) for browser in browsers]
            responses = [future.result(timeout=FUTURE_WAIT) for future in futures]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertCountEqual([response.status_code for response in responses], [200, 409])
        self.assert_real_serialization()
        self.assert_no_identity_cookies(next(response for response in responses if response.status_code == 409))

    def test_two_returns_with_one_version_have_exactly_one_winner(self):
        self.enter_flow()
        version = self.version()
        browsers = [copy_browser(self.client), copy_browser(self.client)]
        barrier = Barrier(2)
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            futures = [pool.submit(self.worker, lambda browser=browser: self.post_json(
                "/api/auth/return-admin/", {}, version=version, client=browser
            ), barrier=barrier) for browser in browsers]
            responses = [future.result(timeout=FUTURE_WAIT) for future in futures]
        finally:
            barrier.abort()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertCountEqual([response.status_code for response in responses], [200, 409])
        self.assert_real_serialization()
        winning_index = next(index for index, response in enumerate(responses) if response.status_code == 200)
        winner = browsers[winning_index]
        returned_version = self.assert_switch_state(responses[winning_index], active=False, can_return=False, user=self.admin)
        self.assertNotEqual(returned_version, version)
        loser = responses[1 - winning_index]
        self.assert_no_identity_cookies(loser)
        self.apply_identity_cookies(loser, winner)
        self.assertEqual(self.version(winner), returned_version)
        self.assertEqual(winner.get("/api/v1/").status_code, 428)
        self.assertEqual(winner.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version).status_code, 409)
        business = winner.get("/api/v1/", HTTP_X_IDENTITY_VERSION=returned_version)
        self.assertEqual(business.status_code, 403, business.content)  # Admin has no Employee.
        usable = winner.get("/admin/", HTTP_X_IDENTITY_VERSION=returned_version)
        self.assertEqual(usable.status_code, 200, usable.content)

    def test_business_permission_scope_and_identity_cannot_mix_during_switch(self):
        alice_view = self.grant_saved_views(self.employee)
        bob_view = self.grant_saved_views(self.other_employee)
        self.enter_flow()
        old_version = self.version()
        reading_browser = copy_browser(self.client)
        switching_browser = copy_browser(self.client)
        in_business = Event()
        release_business = Event()
        switch_lock_attempt = Event()
        identity_samples = []
        original_queryset = SavedViewViewSet.get_queryset

        def paused_queryset(view):
            identity_samples.append(("before", view.request.user.pk, view.actor_employee().pk))
            in_business.set()
            if not release_business.wait(timeout=WAIT):
                raise AssertionError("Timed out waiting to release existing business queryset")
            queryset = original_queryset(view)
            identity_samples.append(("after", view.request.user.pk, view.actor_employee().pk))
            return queryset

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(SavedViewViewSet, "get_queryset", paused_queryset):
                business_future = pool.submit(self.worker, lambda: reading_browser.get(
                    "/api/v1/saved-views/", HTTP_X_IDENTITY_VERSION=old_version))
                self.assertTrue(in_business.wait(timeout=WAIT), "Business request never reached its real queryset")
                switch_future = pool.submit(self.worker, lambda: self.post_json(
                    "/api/auth/switch/", {"employee_id": str(self.other_employee.pk)},
                    version=old_version, client=switching_browser,
                ), lock_attempt=switch_lock_attempt)
                self.assertTrue(switch_lock_attempt.wait(timeout=WAIT), "Switch did not attempt PostgreSQL chain lock")
                self.assertFalse(switch_future.done(), "Switch crossed an in-flight business critical section")
                release_business.set()
                business_response = business_future.result(timeout=FUTURE_WAIT)
                switched = switch_future.result(timeout=FUTURE_WAIT)
        finally:
            release_business.set()
            pool.shutdown(wait=True, cancel_futures=True)
        new_version = self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        self.assertEqual(self.saved_view_ids(business_response), {str(alice_view.pk)})
        self.assertEqual(identity_samples, [
            ("before", self.employee.user_id, self.employee.pk),
            ("after", self.employee.user_id, self.employee.pk),
        ])
        self.assert_real_serialization()
        self.assert_no_identity_cookies(business_response)
        self.apply_identity_cookies(business_response, switching_browser)
        self.assertEqual(self.version(switching_browser), new_version)
        current = switching_browser.get("/api/v1/saved-views/", HTTP_X_IDENTITY_VERSION=new_version)
        self.assertEqual(self.saved_view_ids(current), {str(bob_view.pk)})
        self.assertEqual(switching_browser.get("/api/v1/saved-views/", HTTP_X_IDENTITY_VERSION=old_version).status_code, 409)

    def test_delayed_old_me_response_cannot_overwrite_new_identity_cookies(self):
        self.enter_flow()
        old_version = self.version()
        old_browser = copy_browser(self.client)
        new_browser = copy_browser(self.client)
        in_payload = Event()
        release_payload = Event()
        switch_lock_attempt = Event()
        original_payload = auth_views.user_payload

        def paused_payload(user):
            if user.pk == self.employee.user_id:
                in_payload.set()
                if not release_payload.wait(timeout=WAIT):
                    raise AssertionError("Timed out waiting to release real user payload")
            return original_payload(user)

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(auth_views, "user_payload", paused_payload):
                old_future = pool.submit(self.worker, lambda: old_browser.get("/api/auth/me/"))
                self.assertTrue(in_payload.wait(timeout=WAIT))
                switch_future = pool.submit(self.worker, lambda: self.post_json(
                    "/api/auth/switch/", {"employee_id": str(self.other_employee.pk)},
                    version=old_version, client=new_browser,
                ), lock_attempt=switch_lock_attempt)
                self.assertTrue(switch_lock_attempt.wait(timeout=WAIT))
                self.assertFalse(switch_future.done())
                release_payload.set()
                delayed_response = old_future.result(timeout=FUTURE_WAIT)
                switched = switch_future.result(timeout=FUTURE_WAIT)
        finally:
            release_payload.set()
            pool.shutdown(wait=True, cancel_futures=True)
        new_version = self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        self.assertEqual(delayed_response.data["user"]["id"], self.employee.user_id)
        self.assertEqual(delayed_response.data["account_switch"]["identity_version"], old_version)
        self.assert_real_serialization()
        self.assert_no_identity_cookies(delayed_response)
        latest_session = new_browser.cookies[settings.SESSION_COOKIE_NAME].value
        self.apply_identity_cookies(delayed_response, new_browser)
        self.assertEqual(new_browser.cookies[settings.SESSION_COOKIE_NAME].value, latest_session)
        self.assertEqual(self.version(new_browser), new_version)
        self.assertEqual(new_browser.get("/api/auth/me/").data["user"]["id"], self.other_employee.user_id)
        # A request delayed until after the transition cannot resurrect the old
        # session, clear the new browser's cookie, or perform old-version work.
        stale_business = old_browser.get("/api/v1/", HTTP_X_IDENTITY_VERSION=old_version)
        self.assertEqual(stale_business.status_code, 409, stale_business.content)
        self.assert_no_identity_cookies(stale_business)
        self.apply_identity_cookies(stale_business, new_browser)
        self.assertEqual(self.version(new_browser), new_version)

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_switch_waits_until_real_ordinary_response_session_save_has_finished(self):
        self.enter_flow()
        old_version = self.version()
        old_current = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        reading_browser = copy_browser(self.client)
        switching_browser = copy_browser(self.client)
        before_save = Event()
        release_before_save = Event()
        after_save = Event()
        release_after_save = Event()
        switch_lock_attempt = Event()
        saves = []
        original_save = SessionStore.save

        def observed_real_save(store, *args, **kwargs):
            if store.session_key != old_current:
                return original_save(store, *args, **kwargs)
            before_save.set()
            if not release_before_save.wait(timeout=WAIT):
                raise AssertionError("Timed out before real ordinary-response session save")
            result = original_save(store, *args, **kwargs)
            saves.append(store.session_key)
            after_save.set()
            if not release_after_save.wait(timeout=WAIT):
                raise AssertionError("Timed out after real ordinary-response session save")
            return result

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(SessionStore, "save", observed_real_save):
                ordinary_future = pool.submit(self.worker, lambda: reading_browser.get(
                    "/api/v1/", HTTP_X_IDENTITY_VERSION=old_version))
                self.assertTrue(before_save.wait(timeout=WAIT), "Ordinary response did not reach SessionMiddleware.save")
                switch_future = pool.submit(self.worker, lambda: self.post_json(
                    "/api/auth/switch/", {"employee_id": str(self.other_employee.pk)},
                    version=old_version, client=switching_browser,
                ), lock_attempt=switch_lock_attempt)
                self.assertTrue(switch_lock_attempt.wait(timeout=WAIT))
                self.assertFalse(switch_future.done(), "Switch escaped lock before ordinary response save")
                release_before_save.set()
                self.assertTrue(after_save.wait(timeout=WAIT), "The real PostgreSQL session save did not finish")
                self.assertFalse(switch_future.done(), "Switch escaped lock while ordinary response save was unwinding")
                release_after_save.set()
                ordinary = ordinary_future.result(timeout=FUTURE_WAIT)
                switched = switch_future.result(timeout=FUTURE_WAIT)
        finally:
            release_before_save.set()
            release_after_save.set()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assertEqual(saves, [old_current])
        self.assertEqual(ordinary.status_code, 200, ordinary.content)
        self.assert_no_authentication_cookies(ordinary)
        new_version = self.assert_switch_state(switched, active=True, can_return=True, user=self.other_employee.user)
        self.assert_real_serialization()
        self.assertNotEqual(old_version, new_version)
        self.assertEqual(self.version(switching_browser), new_version)

    def test_business_500_releases_advisory_lock_before_worker_connection_closes(self):
        from apps.core.identity_switch_services import lock_number

        self.grant_saved_views(self.employee)
        self.enter_flow()
        version = self.version()
        browser = copy_browser(self.client)
        browser.raise_request_exception = False
        failure_returned = Event()
        release_failed_worker = Event()
        number = lock_number(self.root_key)

        def failing_request_while_keeping_connection_open():
            physical = connection.connection
            response = browser.get("/api/v1/saved-views/", HTTP_X_IDENTITY_VERSION=version)
            self.assertEqual(response.status_code, 500, response.content)
            self.assertIs(connection.connection, physical, "Physical connection closed before lock-release verification")
            self.assertFalse(physical.closed)
            failure_returned.set()
            if not release_failed_worker.wait(timeout=WAIT):
                raise AssertionError("Timed out keeping failed worker's PostgreSQL connection open")
            return response

        def try_lock_from_independent_connection():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [number])
                acquired = cursor.fetchone()[0]
                try:
                    self.assertTrue(acquired, "Business exception leaked a lock on its still-open connection")
                finally:
                    if acquired:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", [number])
                        self.assertTrue(cursor.fetchone()[0])
            return acquired

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            with patch.object(SavedViewViewSet, "get_queryset", side_effect=RuntimeError("Intentional business failure")):
                failed_future = pool.submit(self.worker, failing_request_while_keeping_connection_open)
                self.assertTrue(failure_returned.wait(timeout=WAIT), "Business request never returned its expected 500")
                self.assertFalse(failed_future.done(), "Original worker must keep its physical connection alive")
                probe_future = pool.submit(self.worker, try_lock_from_independent_connection)
                self.assertTrue(probe_future.result(timeout=FUTURE_WAIT))
                self.assertFalse(failed_future.done())
                release_failed_worker.set()
                failed = failed_future.result(timeout=FUTURE_WAIT)
        finally:
            release_failed_worker.set()
            pool.shutdown(wait=True, cancel_futures=True)
        self.assert_no_authentication_cookies(failed)
        self.assertGreaterEqual(len(set(self.worker_pids)), 2)
        self.assertTrue(self.lock_calls, "Failed business request never acquired its real chain lock")
        self.assertEqual(self.version(), version)
        self.assertEqual(self.client.get("/api/v1/", HTTP_X_IDENTITY_VERSION=version).status_code, 200)

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
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings

from apps.core import views as auth_views
from apps.preferences.api.views import SavedViewViewSet

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
                if "pg_advisory_lock(" in sql.lower():
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

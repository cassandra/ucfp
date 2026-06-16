import os
from unittest.mock import patch

from django.test import TestCase

from background.startup import BackgroundTaskHelper as B

_GUARD_ENV = ('DJANGO_MANAGEMENT_COMMAND', 'RUN_MAIN', 'SERVER_SOFTWARE')


class BackgroundStartupTest(TestCase):

    def setUp(self):
        self._reset()

    def tearDown(self):
        self._reset()

    def _reset(self):
        B._initializers, B._signal_connected, B._started = [], False, False
        for key in _GUARD_ENV:
            os.environ.pop(key, None)

    def test_is_management_command(self):
        self.assertFalse(B.is_management_command())
        os.environ['DJANGO_MANAGEMENT_COMMAND'] = 'migrate'
        self.assertTrue(B.is_management_command())

    def test_is_gunicorn(self):
        self.assertFalse(B._is_gunicorn())
        os.environ['SERVER_SOFTWARE'] = 'gunicorn/21.2'
        self.assertTrue(B._is_gunicorn())

    def test_should_start_only_in_runserver_serving_child(self):
        self.assertFalse(B._should_start_in_this_process())          # no RUN_MAIN
        os.environ['RUN_MAIN'] = 'true'
        self.assertTrue(B._should_start_in_this_process())           # the serving child
        os.environ['DJANGO_MANAGEMENT_COMMAND'] = 'test'
        self.assertFalse(B._should_start_in_this_process())          # management command
        os.environ.pop('DJANGO_MANAGEMENT_COMMAND')
        os.environ['SERVER_SOFTWARE'] = 'gunicorn'
        self.assertFalse(B._should_start_in_this_process())          # gunicorn uses post_fork

    def test_start_with_empty_registry_is_noop(self):
        with patch('background.startup.start_event_loop') as mock_start:
            B.start_background_tasks()
        self.assertEqual(mock_start.call_count, 0)
        self.assertTrue(B._started)

    def test_start_runs_each_registered_task_once(self):
        async def fake():
            return

        B.register(fake, pass_event_loop=False)
        with patch('background.startup.start_event_loop') as mock_start:
            B.start_background_tasks()
            B.start_background_tasks()   # idempotent
        self.assertEqual(mock_start.call_count, 1)

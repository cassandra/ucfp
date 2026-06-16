"""
Reliable startup of long-running background tasks.

Launching a forever-running task at Django startup is deceptively hard, and the
"obvious" approaches all fail:

  - ``AppConfig.ready()`` is TOO EARLY. Django is not fully initialized; threads
    / event loops spawned there die or corrupt startup.
  - ``time.sleep()`` in ready() does not help -- it just blocks (and interferes
    with) initialization.
  - Under ``runserver``, ready() runs in MORE THAN ONE process (the autoreload
    parent and the serving child); only the child has ``RUN_MAIN="true"``.
  - Under gunicorn, ready() effectively does not run for this purpose; startup
    must be driven from gunicorn's post-fork worker hook instead.

What actually works -- two entry points, selected by how the server is run:

  1. ``runserver`` (dev): arm on the FIRST REQUEST. An app calls
     ``BackgroundTaskHelper.start_background_tasks_delayed()`` from its
     ``AppConfig.ready()``; we connect to the ``request_started`` signal and
     start the tasks when the first request arrives. Adds a little first-request
     latency, but it is the only reliable moment.

  2. gunicorn (prod): start in the ``post_worker_init`` hook (see
     ``src/bin/docker-gunicorn.conf.py``), which runs after each worker forks
     and the app is fully initialized.

All the "should we even arm in THIS process?" judgement is consolidated into
``_should_start_in_this_process()`` so app ready() methods stay trivial.

Usage -- an app with a background task does, in its ``AppConfig.ready()``:

    def ready(self):
        from background.startup import BackgroundTaskHelper
        BackgroundTaskHelper.register( MyManager().initialize )
        BackgroundTaskHelper.start_background_tasks_delayed()

With nothing registered the whole mechanism is a no-op -- it exists, ready and
documented, for when the project needs it. The supporting machinery
(``start_event_loop``, ``TaskMonitor``, ``DatabaseLock``) lives in this same
``background`` package; this module is import-usable without adding ``background``
to ``INSTALLED_APPS`` (only ``DatabaseLock`` needs the app installed).
"""
import logging
import os
import sys

from django.core.signals import request_started

from .event_loop import start_event_loop

logger = logging.getLogger(__name__)


class BackgroundTaskHelper:

    _initializers = []          # list of ( task_function, pass_event_loop )
    _signal_connected = False
    _started = False

    @classmethod
    def register( cls, task_function, *, pass_event_loop = True ):
        """
        Register a startup task. ``task_function`` is an async callable run
        forever on its own event loop; with ``pass_event_loop`` it receives that
        loop as its sole argument. Call from an app's ``AppConfig.ready()``,
        before ``start_background_tasks_delayed()``.
        """
        cls._initializers.append( ( task_function, pass_event_loop ) )
        return

    @classmethod
    def start_background_tasks_delayed( cls ):
        """
        Arm the ``runserver`` path: start registered tasks on the first request.
        No-op in the contexts where we must not start here -- one-shot management
        commands, the non-serving runserver process, and under gunicorn (which
        uses ``post_worker_init`` instead).
        """
        if not cls._should_start_in_this_process():
            return
        if cls._signal_connected:
            return
        request_started.connect( cls._on_first_request, weak = False )
        cls._signal_connected = True
        return

    @classmethod
    def _on_first_request( cls, sender, **kwargs ):
        cls.start_background_tasks()
        return

    @classmethod
    def start_background_tasks( cls ):
        """
        Start the registered tasks, each on its own background event loop.
        Idempotent. Called by the runserver first-request signal and directly by
        gunicorn's ``post_worker_init`` hook.
        """
        if cls._signal_connected:
            request_started.disconnect( cls._on_first_request )
            cls._signal_connected = False
        if cls._started:
            return
        for task_function, pass_event_loop in cls._initializers:
            logger.info( 'Starting background task: %s',
                         getattr( task_function, '__qualname__', task_function ) )
            start_event_loop( task_function = task_function, pass_event_loop = pass_event_loop )
            continue
        cls._started = True
        return

    @classmethod
    def _should_start_in_this_process( cls ) -> bool:
        if cls.is_management_command():
            return False
        # Under runserver, ready() runs in multiple processes during startup;
        # only the autoreloader's serving child sets RUN_MAIN="true".
        if os.environ.get( 'RUN_MAIN' ) != 'true':
            return False
        # Under gunicorn, do NOT arm here -- post_worker_init drives startup.
        if cls._is_gunicorn():
            return False
        return True

    @classmethod
    def is_management_command( cls ) -> bool:
        """
        True during a one-shot management command (migrate, test, shell, ...).
        manage.py sets ``DJANGO_MANAGEMENT_COMMAND`` for every non-runserver
        invocation; gunicorn / wsgi never go through manage.py, so the server
        runs tasks. (Not a Django-provided variable -- we set it ourselves.)
        """
        return os.environ.get( 'DJANGO_MANAGEMENT_COMMAND' ) is not None

    @classmethod
    def _is_gunicorn( cls ) -> bool:
        return ( 'gunicorn' in os.environ.get( 'SERVER_SOFTWARE', '' )
                 or 'gunicorn' in sys.argv[0] )

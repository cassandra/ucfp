"""
Cross-worker mutual exclusion using the database as the shared medium.

This is deliberately database-backed (rather than a Redis or OS primitive) so
it works in any deployment that has a database -- including single-file SQLite
-- with no extra infrastructure. It is the coordination primitive for the
background-process machinery: e.g. ensuring only one worker runs a startup
initialization, or that a long-running sync does not overlap itself across
workers/containers.

The DatabaseLock model lives here (re-exported by models.py for Django's model
discovery) so all lock-related code sits in one module.
"""
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone


class DatabaseLock(models.Model):

    name = models.CharField(
        max_length = 64,
        unique = True,
    )
    acquired_at = models.DateTimeField(
    )
    initialized = models.BooleanField(
        default = False,
    )

    class Meta:
        verbose_name = 'Database Lock'
        verbose_name_plural = 'Database Locks'

    def is_expired( self, timeout_seconds = 300 ):
        return timezone.now() > self.acquired_at + timedelta( seconds = timeout_seconds )

    @classmethod
    def acquire( cls,
                 name             : str,
                 timeout_seconds  : int  = 300 ):
        """
        Acquire the named lock, returning the lock row on success or None if it
        is currently held by another worker.

        Acquisition hinges on which caller CREATED the row:
          - If we created it, we hold the lock.
          - If it already existed but has expired (a previous holder crashed
            without releasing), we steal it and hold the lock.
          - Otherwise another worker holds it within the timeout window, so we
            cannot acquire and return None (callers fail-fast or skip).

        The unique-name constraint plus the surrounding atomic transaction
        serialize creation across workers on SQLite and Postgres/MySQL alike:
        the loser of a creation race sees created=False and falls through to
        the held-by-someone-else case.
        """
        with transaction.atomic():
            lock, created = cls.objects.get_or_create(
                name = name,
                defaults = {
                    'acquired_at': timezone.now(),
                    'initialized': False,
                }
            )

            if created:
                return lock

            if lock.is_expired( timeout_seconds ):
                # Previous holder never released (e.g. crashed); take it over.
                lock.acquired_at = timezone.now()
                lock.initialized = False
                lock.save()
                return lock

            # Held by another worker, still within the timeout window.
            return None

    def release(self):
        self.delete()
        return

    def mark_initialized(self):
        self.initialized = True
        self.save()
        return


class ExclusionLockContext:
    """ Basic mutual exclusion lock using the database. """

    def __init__( self, name, timeout_seconds = 300 ):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.lock = None

    def __enter__(self):

        self.lock = DatabaseLock.acquire( name = self.name,
                                          timeout_seconds = self.timeout_seconds )
        if self.lock:
            return self.lock
        else:
            raise RuntimeError(f'Could not acquire lock: {self.name}')

    def __exit__( self, exc_type, exc_val, exc_tb ):
        if self.lock:
            self.lock.release()
        return


class InitializationLockContext:
    """
    Run-once-across-workers guard for startup initialization.

    Only the worker that creates the lock enters the block; any other worker
    racing for the same lock within the timeout window cannot acquire it and
    raises RuntimeError (wrap the `with` in a try/except to skip). Unlike
    ExclusionLockContext, the lock row is NOT released on exit -- it is marked
    initialized and left in place, so the work is not repeated until the lock
    expires (a later restart re-runs it). The `initialized` flag is advisory
    (e.g. visible in the admin); acquisition is decided purely by who holds the
    live lock.
    """

    def __init__( self, name, timeout_seconds = 300 ):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.lock = None

    def __enter__(self):

        self.lock = DatabaseLock.acquire( name = self.name,
                                          timeout_seconds = self.timeout_seconds )
        if self.lock:
            return self.lock
        else:
            raise RuntimeError(f'Could not acquire lock: {self.name}')

    def __exit__( self, exc_type, exc_val, exc_tb ):
        if self.lock:
            self.lock.mark_initialized()
        return

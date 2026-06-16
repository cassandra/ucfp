import threading
import time

from common.singleton import Singleton
from testing.base_test_case import BaseTestCase


class _SlowInitSingleton(Singleton):
    """Mimics a real manager whose ``__init_singleton__`` does blocking I/O
    (e.g. a Redis connect) and sets its last attribute only after that
    blocking step -- the exact shape that exposed the unsafe-publication
    race in ``Singleton.__new__``."""

    init_count = 0

    def __init_singleton__(self):
        type(self).init_count += 1
        # Stand-in for the multi-step / blocking init window during which
        # the instance must NOT be observable by other threads.
        time.sleep(0.05)
        self.ready_attribute = 'ready'   # set LAST, like ``_redis_client``


class SingletonConcurrencyTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        # Isolate from any prior construction.
        _SlowInitSingleton._instance = None
        _SlowInitSingleton.init_count = 0

    def test_no_half_initialized_instance_under_concurrent_access(self):
        """Concurrent first-time callers must never receive an instance
        whose ``__init_singleton__`` has not finished. With the old
        publish-before-init order, threads racing the initializer read the
        last-set attribute before it existed (AttributeError); the fix
        publishes only after initialization completes."""
        thread_count = 12
        barrier = threading.Barrier( thread_count )
        errors = []
        instance_ids = []

        def worker():
            barrier.wait()   # release all threads simultaneously for max contention
            try:
                instance = _SlowInitSingleton()
                # Reading the attribute set on the final init line must
                # never raise -- that is the regression being guarded.
                _ = instance.ready_attribute
                instance_ids.append( id( instance ) )
            except Exception as e:   # noqa: BLE001 -- capture for assertion
                errors.append( repr( e ) )

        threads = [ threading.Thread( target = worker ) for _ in range( thread_count ) ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual( errors, [], 'No thread should observe a half-initialized instance' )
        self.assertEqual( _SlowInitSingleton.init_count, 1, 'Initializer must run exactly once' )
        self.assertEqual( len( set( instance_ids ) ), 1, 'All callers must share one instance' )
        self.assertEqual( len( instance_ids ), thread_count )

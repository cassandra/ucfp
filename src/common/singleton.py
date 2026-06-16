from threading import Lock

# Global dictionary to store locks for each singleton class
_singleton_locks = {}


class Singleton:
    _instance = None

    def __new__(cls):
        # Fast path: the instance is published (below) only AFTER
        # __init_singleton__ has fully run, so a non-None value here is
        # always safe to return without locking.
        if cls._instance is not None:
            return cls._instance

        # ``setdefault`` is atomic under the GIL, so concurrent first-time
        # callers agree on a single per-class lock (the plain
        # ``if cls not in ...: ... = Lock()`` form could create two).
        lock = _singleton_locks.setdefault( cls, Lock() )

        with lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                # Initialize BEFORE publishing. A concurrent caller either
                # sees ``None`` (and blocks on ``lock``) or a fully-built
                # instance -- never a half-initialized one. Publishing the
                # reference first (the old behavior) let other threads
                # return the instance mid-__init_singleton__, e.g. before a
                # blocking Redis connect had set an attribute.
                instance.__init_singleton__()
                cls._instance = instance
        return cls._instance

    def __init_singleton__(self):
        """ Subclasses can override this if needed. """
        return


class SingletonSync:
    """ Simpler version without multithread/asyncio initialization protections. """
    _instance = None

    def __new__( cls ):
        if cls._instance is None:
            cls._instance = super().__new__( cls )
            cls._instance.__init_singleton__()
        return cls._instance

    def __init_singleton__(self):
        """ Subclasses can override this if needed. """
        return

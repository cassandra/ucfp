"""Process-local cache of a captured run's reloaded books, keyed by the immutable books record.

Rebuilding a run's `BooksOfAccount` from its stored rows is the dominant cost on the display path --
field decryption plus domain-graph construction, all CPU-bound. A captured run's books are immutable,
so every view that shows the run reloads a byte-identical graph: the results page, and -- felt most --
each books-table column operation (expand / collapse / hide / reorder), which today re-runs the whole
reload on every click. This memoizes that reload so the repeated views become a lookup; only the first
view of a run pays the load.

Bounded to a few recently-shown runs (LRU). Each graph is large (~8-16 MB), so the bound keeps the
memory modest on a small host -- a handful covers the working set of a light, few-user load, with a
hard ceiling regardless of traffic.

Process-local by design: correctness never depends on process affinity -- a miss simply reloads -- so
under multiple workers or instances this degrades gracefully to partial hit-rates (sticky sessions
help, and a shared Redis cache is the later lever if multi-process hit-rates ever justify the cost of
serializing the graph). It is not relied on for a single process.

The returned books is SHARED and must be treated as read-only: the display path only reads it (its
`Bookkeeper` / `Ledger` build their own indices over it and never mutate it). It must never be handed
to code that records, posts, or otherwise mutates the books -- the engine builds its own books and does
not use this cache.
"""
from collections import OrderedDict
from threading import Lock

from ucfp.accounts.repository import BooksOfAccountRepository


# Recently-shown runs kept warm. At ~8-16 MB per graph this bounds the cache to roughly 50-100 MB --
# comfortable on a 2 GB host under the expected light load, and a firm ceiling however many distinct
# runs are browsed.
_MAX_CACHED_RUNS = 6

_books_by_uuid : "OrderedDict" = OrderedDict()   # books uuid -> BooksOfAccount (LRU: newest at the end)
_lock = Lock()


def load_run_books( books_record ):
    """The reloaded `BooksOfAccount` for `books_record`, served from the process-local cache when warm.

    On a miss the reload runs OUTSIDE the lock, so a slow reload never blocks other requests and two
    simultaneous misses for one run simply both reload (rare, and harmless -- they build equal graphs).
    Keyed by the record's uuid, which is globally unique, so a reused primary key -- e.g. across test
    runs sharing a process -- can never serve another run's books."""
    key = books_record.uuid
    with _lock:
        cached = _books_by_uuid.get( key )
        if cached is not None:
            _books_by_uuid.move_to_end( key )
            return cached
    books = BooksOfAccountRepository().load( books_record )
    with _lock:
        _books_by_uuid[ key ] = books
        _books_by_uuid.move_to_end( key )
        while len( _books_by_uuid ) > _MAX_CACHED_RUNS:
            _books_by_uuid.popitem( last = False )
    return books


def clear_run_books_cache() -> None:
    """Drop every cached books. Ordinary operation needs no invalidation -- captured run books are
    immutable -- so this is for test hygiene and any future explicit-eviction need."""
    with _lock:
        _books_by_uuid.clear()

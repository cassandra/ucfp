# The DatabaseLock model is defined in locks.py alongside its context managers
# (all lock-related code in one module). It is re-exported here so Django's
# model discovery -- which imports each app's `models` module -- registers it.
from .locks import DatabaseLock  # noqa: F401

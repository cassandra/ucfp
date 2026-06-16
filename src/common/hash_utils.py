import hashlib

from django.conf import settings


def hash_with_seed( value : str ):
    """
    Hash a string in a moderately secure way using a seed value that someone
    has to have access to. most used to support email unsubscribing without
    the need to login.
    """
    seed = settings.SECRET_KEY
    m = hashlib.sha256()
    m.update( seed.encode('utf-8') )
    m.update( str(value).encode('utf-8') )
    return m.hexdigest()

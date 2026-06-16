import re
from urllib import parse as urllib_parse


def is_safe_redirect_url(url: str) -> bool:
    """
    Validate that a redirect URL is safe (internal path only).
    Prevents open redirect attacks.
    """
    if not url:
        return False

    # Only allow relative paths starting with /
    if not url.startswith('/'):
        return False

    # Reject protocol-relative URLs (//example.com)
    if url.startswith('//'):
        return False

    return True


def url_simplify( text : str ):
    """ For creating readable, but simple url labels from text. """
    if not text:
        return ''
    return re.sub( r'[\W]+', '-', text.lower() ).rstrip('-').lstrip('-')


def get_url_top_level_domain( url_str : str, default_value : str = None ):

    hostname = urllib_parse.urlparse( url_str ).hostname
    if not hostname:
        return default_value

    parts = hostname.split('.')
    if len(parts) < 2:
        return default_value

    if len(parts) < 3:
        return hostname

    return f'{parts[-2]}.{parts[-1]}'

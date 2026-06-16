import re


REPLACE_URL_REGEX = re.compile( r"((https?):((//)|(\\\\))+[\w\d:#@%/;$()~_?\+-=\\\.&]*)",
                                re.MULTILINE | re.UNICODE )


def is_blank( obj ):
    if obj is None:
        return True
    if not isinstance( obj, str ):
        return False
    return bool( obj.strip() == '' )


def str_to_bool( value: str ) -> bool:
    if isinstance( value, bool ):
        return value
    truthy_values = {'true', '1', 'on', 'yes', 'y', 't', 'enabled'}
    if isinstance( value, str ):
        return value.strip().lower() in truthy_values
    return False


def replace_url_text_with_html_anchor( value : str, use_link_text : bool = True ):
    if not value:
        return value
    try:
        if use_link_text:
            value = REPLACE_URL_REGEX.sub(r'<a href="\1" target="_blank">LINK</a>', value)
        else:
            value = REPLACE_URL_REGEX.sub(r'<a href="\1" target="_blank">\1</a>', value)
        return value

    except Exception:
        # We never want this to fail and do not care that much if it does.
        return value


def to_dict_or_none( obj ):
    if obj is None:
        return None
    return obj.to_dict()

def get_humanized_secs( sec_elapsed ):

    if sec_elapsed < 1:
        return '0 secs'

    days = int(sec_elapsed / (24 * 60 * 60))
    hours = int(sec_elapsed % (24 * 60 * 60) / (60 * 60))
    minutes = int((sec_elapsed % (60 * 60)) / 60)
    seconds = int(sec_elapsed % 60.0)

    components = []
    if days > 1:
        components.append( f'{days} days' )
    elif days > 0:
        components.append( f'{days} day' )

    if hours > 1:
        components.append( f'{hours} hrs' )
    elif hours > 0:
        components.append( f'{hours} hr' )

    if minutes > 1:
        components.append( f'{minutes} mins' )
    elif minutes > 0:
        components.append( f'{minutes} min' )

    if seconds > 1:
        components.append( f'{seconds} secs' )
    elif seconds > 0:
        components.append( f'{seconds} sec' )

    return ', '.join( components )


def get_humanized_number( value ):
    if value == 0:
        return 'zero'
    if (( value % 100 ) > 10 ) and (( value % 100 ) < 20 ):
        return f'{value:,}th'
    if ( value % 10 ) == 1:
        return f'{value:,}st'
    if ( value % 10 ) == 2:
        return f'{value:,}nd'
    if ( value % 10 ) == 3:
        return f'{value:,}rd'
    return f'{value:,}th'

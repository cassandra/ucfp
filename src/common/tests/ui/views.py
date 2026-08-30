from django.shortcuts import render
from django.views.generic import View

from common.templatetags.icons import AVAILABLE_ICONS, ICON_COLORS, ICON_SIZES


class TestUiCommonHomeView( View ):

    def get( self, request, *args, **kwargs ):
        return render( request, 'common/tests/ui/home.html', {} )


class TestUiIconBrowserView( View ):
    """
    Auto-discovery view for browsing every available icon. Any icon added to
    ``AVAILABLE_ICONS`` shows up here automatically -- no manual updates.
    """

    def get( self, request, *args, **kwargs ):
        icon_name_list = sorted( AVAILABLE_ICONS )
        context = {
            'icon_name_list' : icon_name_list,
            'size_list'      : sorted( ICON_SIZES ),
            'color_list'     : sorted( ICON_COLORS ),
            'total_icons'    : len( AVAILABLE_ICONS ),
        }
        return render( request, 'common/tests/ui/icon_browser.html', context )

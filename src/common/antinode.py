"""
Helper routines for antinode.js when using this for AJAX-y things.
Normally you can just set the tag attributes data-async
when it is a simple call and replace, but for alternative response flows
these routines provide the convenience wrappers around the antinode.js
specific things.
"""
import json

from django.http import HttpResponse, HttpRequest
from django.template.loader import get_template


def normalize_content( content: HttpResponse | str ) -> str:
    if isinstance( content, HttpResponse ):
        return content.content.decode('utf-8')
    if isinstance( content, str ):
        return content
    raise ValueError( f'Unknown content type. Cannot normalize for async response: {content}.' )


def http_response( data: dict, status: int = 200 ) -> HttpResponse:
    return HttpResponse( json.dumps( data ),
                         content_type = 'application/json',
                         status = status )


def modal_from_content( request: HttpRequest,
                        content: HttpResponse | str,
                        status: int = 200 ) -> HttpResponse:
    """
    Display the given content inside a modal (instead of replacing the
    data-async target). Use when the data-async target was not itself a modal.
    """
    return http_response( { 'modal': normalize_content( content ) }, status = status )


def modal_from_template( request: HttpRequest,
                         template_name: str,
                         context: dict | None = None,
                         status: int = 200 ) -> HttpResponse:
    """
    Render template_name and display the result inside a modal (instead of
    replacing the data-async target). The template should contain the modal
    structure (minus the outer wrapper modal div).
    """
    context = context or {}
    template = get_template( template_name )
    content = template.render( context, request = request )
    return modal_from_content( request, content, status = status )


def refresh_response() -> HttpResponse:
    return http_response( { 'refresh': True } )


def redirect_response( url: str ) -> HttpResponse:
    return http_response( { 'location': url } )


def response_as_dict( main_content: HttpResponse | str | None = None,
                      replace_map: dict | None = None,
                      insert_map: dict | None = None,
                      append_map: dict | None = None,
                      set_attributes_map: dict | None = None,
                      modal_content: HttpResponse | str | None = None,
                      push_url: str | None = None,
                      reset_scrollbar: bool = False,
                      scroll_to: str | None = None ) -> dict:
    """
    In concert with the Javascript handling of synchronous replies,
    this will allow returning multiple pieces of content in one reply
    for the cases where the request has altered more than one area
    of the page.  The 'main_content' will be rendered in whatever
    the 'data-async' value that was specified, while the 'replace_map' should
    be a map from an html tag id to the html content to populate.

    The 'replace_map' is a full replacement of the previous content,
    so usually should have the same html tag id as what it replaces.

    The 'insert_map' is used when you only want to replace the contents
    of the given node and not the node itself.

    The 'append_map' is for content you want appended to the given id
    list of child content.

    The 'scroll_to' parameter can be used to automatically scroll to a
    specific element ID after all DOM updates are complete.
    """
    response_dict = {}

    if main_content is not None:
        response_dict['html'] = normalize_content( main_content )
    if replace_map is not None:
        response_dict['replace'] = replace_map
    if insert_map is not None:
        response_dict['insert'] = insert_map
    if append_map is not None:
        response_dict['append'] = append_map
    if set_attributes_map is not None:
        response_dict['setAttributes'] = set_attributes_map
    if modal_content is not None:
        response_dict['modal'] = normalize_content( modal_content )
    if push_url is not None:
        response_dict['pushUrl'] = push_url
    if reset_scrollbar:
        response_dict['resetScrollbar'] = True
    if scroll_to is not None:
        response_dict['scrollTo'] = scroll_to
    return response_dict


def response( main_content: HttpResponse | str | None = None,
              replace_map: dict | None = None,
              insert_map: dict | None = None,
              append_map: dict | None = None,
              set_attributes_map: dict | None = None,
              modal_content: HttpResponse | str | None = None,
              push_url: str | None = None,
              reset_scrollbar: bool = False,
              scroll_to: str | None = None,
              status: int = 200 ) -> HttpResponse:

    response_dict = response_as_dict(
        main_content = main_content,
        replace_map = replace_map,
        insert_map = insert_map,
        append_map = append_map,
        set_attributes_map = set_attributes_map,
        modal_content = modal_content,
        push_url = push_url,
        reset_scrollbar = reset_scrollbar,
        scroll_to = scroll_to,
    )
    return http_response( response_dict, status = status )

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import BadRequest, PermissionDenied, ImproperlyConfigured
from django.http import (
    HttpResponse, JsonResponse, Http404,
    HttpResponseNotAllowed, HttpResponseForbidden,
)
from django.test import TestCase, RequestFactory

from common.exceptions import MethodNotAllowedError
from ucfp.middleware import ExceptionMiddleware, NoStoreMiddleware, SessionStateMiddleware
from ucfp.session_state import SessionState


def _req(ajax=False):
    extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if ajax else {}
    request = RequestFactory().get('/', **extra)
    request.user = AnonymousUser()   # error pages render the auth context processor
    return request


class ExceptionMiddlewareTest(TestCase):

    mw = ExceptionMiddleware(lambda r: HttpResponse())

    def test_process_exception_status_map(self):
        for exc, code in [(BadRequest('b'), 400), (ImproperlyConfigured('c'), 501),
                          (PermissionDenied('p'), 403), (Http404('n'), 404),
                          (MethodNotAllowedError('m'), 405), (ValueError('boom'), 500)]:
            self.assertEqual(self.mw.process_exception(_req(), exc).status_code, code, exc)

    def test_process_response_maps_bare_error_responses(self):
        self.assertEqual(self.mw.process_response(_req(), HttpResponseNotAllowed(['GET'])).status_code, 405)
        self.assertEqual(self.mw.process_response(_req(), HttpResponseForbidden()).status_code, 403)
        self.assertEqual(self.mw.process_response(_req(), HttpResponse('ok')).status_code, 200)

    def test_ajax_error_is_modal_sync_error_is_page(self):
        ajax = self.mw.process_exception(_req(ajax=True), BadRequest('bad input'))
        self.assertEqual(ajax.status_code, 400)
        self.assertIn(b'modal', ajax.content)
        sync = self.mw.process_exception(_req(), BadRequest('bad input'))
        self.assertEqual(sync.status_code, 400)
        self.assertIn(b'<!doctype html>', sync.content)
        self.assertIn(b'bad input', sync.content)


class NoStoreMiddlewareTest(TestCase):

    def _run(self, response):
        return NoStoreMiddleware(lambda r: response)(None)

    def test_html_and_json_get_no_store(self):
        self.assertEqual(self._run(HttpResponse('<p>x</p>', content_type='text/html'))['Cache-Control'],
                         'no-store')
        self.assertEqual(self._run(JsonResponse({'a': 1}))['Cache-Control'], 'no-store')

    def test_static_like_response_untouched(self):
        self.assertFalse(self._run(HttpResponse(b'x', content_type='image/png')).has_header('Cache-Control'))

    def test_existing_cache_control_respected(self):
        response = HttpResponse('x', content_type='text/html')
        response['Cache-Control'] = 'max-age=60'
        self.assertEqual(self._run(response)['Cache-Control'], 'max-age=60')


class SessionStateMiddlewareTest(TestCase):

    def test_attaches_typed_session_state(self):
        request = RequestFactory().get('/')
        seen = {}
        SessionStateMiddleware(
            lambda r: seen.setdefault('v', r.session_state) or HttpResponse()
        )(request)
        self.assertIsInstance(request.session_state, SessionState)
        self.assertIs(seen['v'], request.session_state)

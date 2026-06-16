import json

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, RequestFactory

from common.async_view import AsyncView, ModalView
from common.exceptions import MethodNotAllowedError


def _req(method='get', ajax=False):
    extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if ajax else {}
    request = getattr(RequestFactory(), method)('/', **extra)
    request.user = AnonymousUser()
    return request


class AsyncViewTest(TestCase):

    def _view(self):
        class _V(AsyncView):
            def get_target_div_id(self):
                return 'main'

            def get_template_name(self):
                return 'modals/action_ok.html'

            def get_template_context(self, request, *args, **kwargs):
                return {}
        return _V()

    def test_get_returns_insert_map(self):
        data = json.loads(self._view().get(_req()).content)
        self.assertIn('main', data['insert'])
        self.assertIn('modal-ok', data['insert']['main'])

    def test_post_defaults_to_method_not_allowed(self):
        with self.assertRaises(MethodNotAllowedError):
            self._view().post(_req('post'))


class ModalViewTest(TestCase):

    def _view(self):
        class _M(ModalView):
            def get_template_name(self):
                return 'modals/action_ok.html'
        return _M()

    def test_ajax_returns_modal_json(self):
        resp = self._view().get(_req(ajax=True))
        self.assertIn('modal', json.loads(resp.content))

    def test_sync_returns_full_page_with_modal(self):
        resp = self._view().get(_req())
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'<!doctype html>', resp.content)
        self.assertIn(b'antinode-initial-modal', resp.content)
        self.assertIn(b'modal-ok', resp.content)

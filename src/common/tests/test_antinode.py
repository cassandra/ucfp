import json

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import TestCase, RequestFactory

from common import antinode


class NormalizeContentTest(TestCase):

    def test_str_passthrough(self):
        self.assertEqual(antinode.normalize_content('<p>x</p>'), '<p>x</p>')

    def test_httpresponse_is_decoded(self):
        self.assertEqual(antinode.normalize_content(HttpResponse('<p>y</p>')), '<p>y</p>')

    def test_other_type_raises(self):
        with self.assertRaises(ValueError):
            antinode.normalize_content(123)


class HttpResponseTest(TestCase):

    def test_json_content_type_and_status(self):
        resp = antinode.http_response({'a': 1}, status=201)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp['Content-Type'], 'application/json')
        self.assertEqual(json.loads(resp.content), {'a': 1})


class ModalTest(TestCase):

    def test_modal_from_content(self):
        resp = antinode.modal_from_content(None, '<div>m</div>', status=400)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(json.loads(resp.content), {'modal': '<div>m</div>'})

    def test_modal_from_template_renders_into_modal_key(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        body = json.loads(antinode.modal_from_template(request, 'modals/action_ok.html').content)
        self.assertIn('modal', body)
        self.assertIn('modal-ok', body['modal'])


class SimpleResponsesTest(TestCase):

    def test_refresh(self):
        self.assertEqual(json.loads(antinode.refresh_response().content), {'refresh': True})

    def test_redirect(self):
        self.assertEqual(json.loads(antinode.redirect_response('/go').content), {'location': '/go'})


class ResponseAsDictTest(TestCase):

    def test_full_key_mapping(self):
        result = antinode.response_as_dict(
            main_content='<h>', replace_map={'a': '1'}, insert_map={'b': '2'},
            append_map={'c': '3'}, set_attributes_map={'d': {'k': 'v'}}, modal_content='M',
            push_url='/u', reset_scrollbar=True, scroll_to='#x')
        self.assertEqual(result, {
            'html': '<h>', 'replace': {'a': '1'}, 'insert': {'b': '2'}, 'append': {'c': '3'},
            'setAttributes': {'d': {'k': 'v'}}, 'modal': 'M', 'pushUrl': '/u',
            'resetScrollbar': True, 'scrollTo': '#x'})

    def test_none_omitted_but_empty_dict_kept(self):
        # An explicit empty map is meaningful (None check, not truthiness).
        self.assertEqual(antinode.response_as_dict(insert_map={}), {'insert': {}})
        self.assertEqual(antinode.response_as_dict(), {})

    def test_reset_scrollbar_false_is_omitted(self):
        self.assertNotIn('resetScrollbar', antinode.response_as_dict(reset_scrollbar=False))


class ResponseTest(TestCase):

    def test_wraps_dict_as_json_http_response(self):
        resp = antinode.response(insert_map={'main': 'x'}, status=202)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp['Content-Type'], 'application/json')
        self.assertEqual(json.loads(resp.content), {'insert': {'main': 'x'}})

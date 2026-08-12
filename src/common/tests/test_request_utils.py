from django.test import RequestFactory, SimpleTestCase

from common.request_utils import get_client_ip


class GetClientIpTestCase(SimpleTestCase):

    def setUp(self):
        self.factory = RequestFactory()
        return

    def test_uses_left_most_forwarded_for_entry(self):
        request = self.factory.get( '/', HTTP_X_FORWARDED_FOR = '203.0.113.7, 10.0.0.1, 10.0.0.2' )
        self.assertEqual( get_client_ip( request ), '203.0.113.7' )

    def test_single_forwarded_for_value(self):
        request = self.factory.get( '/', HTTP_X_FORWARDED_FOR = '203.0.113.7' )
        self.assertEqual( get_client_ip( request ), '203.0.113.7' )

    def test_falls_back_to_remote_addr_without_header(self):
        request = self.factory.get( '/' )  # RequestFactory sets REMOTE_ADDR to 127.0.0.1
        self.assertEqual( get_client_ip( request ), '127.0.0.1' )

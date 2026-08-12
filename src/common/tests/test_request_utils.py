from django.test import RequestFactory, SimpleTestCase

from common.request_utils import get_client_ip


class GetClientIpTestCase(SimpleTestCase):

    def setUp(self):
        self.factory = RequestFactory()
        return

    def test_uses_right_most_forwarded_for_entry(self):
        # nginx appends the real peer, so the right-most entry is the trusted one.
        request = self.factory.get( '/', HTTP_X_FORWARDED_FOR = '10.0.0.1, 10.0.0.2, 203.0.113.7' )
        self.assertEqual( get_client_ip( request ), '203.0.113.7' )

    def test_ignores_client_spoofed_left_entries(self):
        # An attacker prepends a fake address; nginx appends the real one. We must
        # take the right-most (nginx-observed), never the attacker-controlled left.
        request = self.factory.get( '/', HTTP_X_FORWARDED_FOR = '1.2.3.4, 203.0.113.7' )
        self.assertEqual( get_client_ip( request ), '203.0.113.7' )

    def test_single_forwarded_for_value(self):
        request = self.factory.get( '/', HTTP_X_FORWARDED_FOR = '203.0.113.7' )
        self.assertEqual( get_client_ip( request ), '203.0.113.7' )

    def test_falls_back_to_remote_addr_without_header(self):
        request = self.factory.get( '/' )  # RequestFactory sets REMOTE_ADDR to 127.0.0.1
        self.assertEqual( get_client_ip( request ), '127.0.0.1' )

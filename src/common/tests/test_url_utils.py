from django.test import TestCase

import common.url_utils as url_utils


class UrlUtilsTestCase(TestCase):

    def test_url_simplify(self):

        data_list = [
            ( None, '' ),
            ( '     ', '' ),
            ( '--,.<>!@#$%^&*(_+=', '_' ),
            ( 'foo', 'foo' ),
            ( 'Foo Bar', 'foo-bar' ),
            ( '   Foo, Bar!  ', 'foo-bar' ),
        ]

        for data in data_list:
            self.assertEqual( data[1], url_utils.url_simplify( data[0] ), data )
            continue
        return

    def test_get_url_top_level_domain(self):

        data_list = [
            ( None, None ),
            ( '', None ),
            ( '     ', None ),
            ( '--,.<>!@#$%^&*(_+=', None ),
            ( 'foo', None ),
            ( 'foo/bar', None ),
            ( '/foo/bar', None ),
            ( 'http://foo/bar', None ),
            ( 'https://foo.com/bar', 'foo.com' ),
            ( 'https://no.foo.com/bar', 'foo.com' ),
            ( 'https://no.yes.foo.com/bar', 'foo.com' ),
        ]

        for data in data_list:
            self.assertEqual( data[1], url_utils.get_url_top_level_domain( data[0] ), data )
            continue
        return

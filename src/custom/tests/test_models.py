from django.contrib.auth import get_user_model
from django.test import TestCase


class CustomUserDisplayNameTestCase(TestCase):

    def setUp(self):
        self.User = get_user_model()
        return

    def test_get_long_display_name(self):

        test_data = [
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     last_name = 'Pampling',
                                                     email = 'sample1@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Pampling, Sampling',
              },
            { 'user': self.User.objects.create_user( last_name = 'Pampling',
                                                     email = 'sample2@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Pampling',
              },
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     email = 'sample3@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Sampling',
              },
            { 'user': self.User.objects.create_user( email = 'sample4@example.com',
                                                     password = 'top_secret' ),
              'expected': 'sample4',
              },
        ]

        for data in test_data:
            result = data['user'].long_display_name
            self.assertEqual( data['expected'], result )
            continue
        return

    def test_get_short_display_name(self):

        test_data = [
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     last_name = 'Pampling',
                                                     email = 'sample1@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Sampling',
              },
            { 'user': self.User.objects.create_user( last_name = 'Pampling',
                                                     email = 'sample2@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Pampling',
              },
            { 'user': self.User.objects.create_user( first_name = 'Sampling',
                                                     email = 'sample3@example.com',
                                                     password = 'top_secret' ),
              'expected': 'Sampling',
              },
            { 'user': self.User.objects.create_user( email = 'sample4@example.com',
                                                     password = 'top_secret' ),
              'expected': 'sample4',
              },
        ]

        for data in test_data:
            result = data['user'].short_display_name
            self.assertEqual( data['expected'], result )
            continue
        return

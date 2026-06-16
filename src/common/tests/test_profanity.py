from django.test import TestCase

import common.profanity as profanity


class ProfanityTestCase(TestCase):

    def test_is_profanity_text(self):

        data_list = [
            ( 'Normal sentence', False ),
            ( 'Normal', False ),
            ( 'tofu ckicken', False ),
            ( 'fuck', True ),
            ( 'fucks', True ),
            ( 'shit', True ),
            ( 'ass', True ),
            ( 'i cannot say fuck?', True ),
            ( 'fuck.this', True ),
        ]

        for text, expected_result in data_list:
            self.assertEqual( expected_result, profanity.is_profanity_text(text), f'{text}' )
            continue
        return

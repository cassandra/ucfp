import logging

from django.test import TestCase

import common.name_utils as name_utils

logging.disable(logging.CRITICAL)


class TestNameUtils(TestCase):

    def test_RandomNameGenerator(self):

        for _ in range(10):
            self.assertTrue( len(name_utils.RandomNameGenerator.next_first_name()) > 2 )
            self.assertTrue( len(name_utils.RandomNameGenerator.next_last_name()) > 2 )
            self.assertTrue( len(name_utils.RandomNameGenerator.next_full_name()) > 2 )
            continue
        return


class TestStripParentNamePrefix(TestCase):
    """``strip_parent_name_prefix`` removes a leading parent-name prefix
    so list contexts that already display the parent name don't repeat
    it on every child row."""

    def test_strips_with_space_separator(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( 'Zoo Heater Fan Mode', 'Zoo Heater' ),
            'Fan Mode',
        )

    def test_strips_with_dash_separator(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( 'Zoo Heater - Fan Mode', 'Zoo Heater' ),
            'Fan Mode',
        )

    def test_case_insensitive_prefix_match(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( 'zoo heater fan mode', 'Zoo Heater' ),
            'fan mode',
        )

    def test_returns_full_when_no_prefix_match(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( 'Outdoor Temperature', 'Zoo Heater' ),
            'Outdoor Temperature',
        )

    def test_returns_full_when_stripping_leaves_nothing(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( 'Zoo Heater', 'Zoo Heater' ),
            'Zoo Heater',
        )

    def test_returns_full_when_parent_name_empty(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( 'Zoo Heater Fan Mode', '' ),
            'Zoo Heater Fan Mode',
        )

    def test_returns_empty_string_when_full_name_empty(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( '', 'Zoo Heater' ),
            '',
        )

    def test_handles_none_full_name(self):
        self.assertEqual(
            name_utils.strip_parent_name_prefix( None, 'Zoo Heater' ),
            '',
        )

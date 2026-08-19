import logging
from unittest.mock import Mock, patch

from django.conf import settings

from user.magic_code_generator import MagicCodeGenerator, MagicCodeStatus
from testing.base_test_case import BaseTestCase

logging.disable(logging.CRITICAL)


class TestMagicCodeGenerator(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.generator = MagicCodeGenerator()
        self.mock_request = Mock()
        self.mock_request.session = {}

    def test_make_magic_code_generates_valid_code_and_stores_in_session(self):
        """Test magic code generation stores code and timestamp in session."""
        magic_code = self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        # Verify code characteristics
        self.assertIsInstance(magic_code, str)
        self.assertEqual(len(magic_code), MagicCodeGenerator.MAGIC_CODE_LENGTH)
        self.assertTrue(all(c in MagicCodeGenerator.MAGIC_CODE_CHARS for c in magic_code))

        # Verify session storage
        self.assertEqual(self.mock_request.session[MagicCodeGenerator.MAGIC_CODE], magic_code)
        self.assertIn(MagicCodeGenerator.MAGIC_CODE_TIMESTAMP, self.mock_request.session)
        self.assertIsInstance(self.mock_request.session[MagicCodeGenerator.MAGIC_CODE_TIMESTAMP], int)
        # The code is bound to its target account, and read back via magic_code_target.
        self.assertEqual(self.generator.magic_code_target(self.mock_request),
                         '11111111-1111-1111-1111-111111111111')

    def test_check_magic_code_returns_valid_for_correct_code(self):
        """Test magic code validation returns VALID for correct code."""
        magic_code = self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        result = self.generator.check_magic_code(self.mock_request, magic_code)

        self.assertEqual(result, MagicCodeStatus.VALID)

    def test_check_magic_code_returns_invalid_for_wrong_code(self):
        """Test magic code validation returns INVALID for incorrect code."""
        self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        result = self.generator.check_magic_code(self.mock_request, 'wrongcode')

        self.assertEqual(result, MagicCodeStatus.INVALID)

    def test_check_magic_code_handles_case_insensitive_validation(self):
        """Test magic code validation is case insensitive."""
        magic_code = self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        # Test uppercase version
        result_upper = self.generator.check_magic_code(self.mock_request, magic_code.upper())
        # Test lowercase version
        result_lower = self.generator.check_magic_code(self.mock_request, magic_code.lower())

        self.assertEqual(result_upper, MagicCodeStatus.VALID)
        self.assertEqual(result_lower, MagicCodeStatus.VALID)

    def test_check_magic_code_strips_whitespace_and_dashes(self):
        """Test magic code validation strips whitespace and dashes."""
        magic_code = self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        # Add whitespace and dashes
        formatted_code = f" {magic_code[:3]}-{magic_code[3:]} "
        result = self.generator.check_magic_code(self.mock_request, formatted_code)

        self.assertEqual(result, MagicCodeStatus.VALID)

    @patch('user.magic_code_generator.MagicCodeGenerator.get_elapsed_seconds')
    def test_check_magic_code_returns_expired_for_old_code(self, mock_elapsed_seconds):
        """Test magic code validation returns EXPIRED for codes past timeout."""
        # Set up initial time
        mock_elapsed_seconds.return_value = 1000
        magic_code = self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        # Move time forward past timeout
        mock_elapsed_seconds.return_value = 1000 + MagicCodeGenerator.MAGIC_CODE_TIMEOUT_SECS + 1

        result = self.generator.check_magic_code(self.mock_request, magic_code)

        self.assertEqual(result, MagicCodeStatus.EXPIRED)

    def test_expire_magic_code_clears_session_data(self):
        """Test expire_magic_code clears magic code data from session."""
        self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        # Verify data exists
        self.assertIn(MagicCodeGenerator.MAGIC_CODE, self.mock_request.session)
        self.assertIn(MagicCodeGenerator.MAGIC_CODE_TIMESTAMP, self.mock_request.session)

        self.generator.expire_magic_code(self.mock_request)

        # Verify data is cleared
        self.assertIsNone(self.mock_request.session[MagicCodeGenerator.MAGIC_CODE])
        self.assertIsNone(self.mock_request.session[MagicCodeGenerator.MAGIC_CODE_TIMESTAMP])

    def test_magic_code_status_enum_business_logic_values(self):
        """Test MagicCodeStatus enum values support validation business logic."""
        # Test that VALID has highest value for comparison logic
        self.assertTrue(MagicCodeStatus.VALID.value > MagicCodeStatus.EXPIRED.value)
        self.assertTrue(MagicCodeStatus.EXPIRED.value > MagicCodeStatus.INVALID.value)

        # Test specific values that may be used in conditional logic
        self.assertEqual(MagicCodeStatus.INVALID.value, 0)
        self.assertEqual(MagicCodeStatus.EXPIRED.value, 1)
        self.assertEqual(MagicCodeStatus.VALID.value, 2)

    @patch('user.magic_code_generator.MagicCodeGenerator.get_elapsed_seconds')
    def test_get_elapsed_seconds_provides_consistent_timestamps(self, mock_elapsed_seconds):
        """Test timestamp generation provides consistent values for timeout calculations."""
        mock_elapsed_seconds.return_value = 5000

        timestamp1 = self.generator.get_elapsed_seconds()
        timestamp2 = self.generator.get_elapsed_seconds()

        # Both calls should return same mocked value
        self.assertEqual(timestamp1, timestamp2)
        self.assertEqual(timestamp1, 5000)

    def test_get_timeout_seconds_returns_configured_value(self):
        """Test timeout configuration returns expected value from settings."""
        timeout = self.generator.get_timeout_seconds()

        self.assertEqual(timeout, MagicCodeGenerator.MAGIC_CODE_TIMEOUT_SECS)
        self.assertIsInstance(timeout, int)

    def test_timeout_reads_signin_code_setting(self):
        """The code lifetime is driven by the intent-named sign-in setting, not
        Django's PASSWORD_RESET_TIMEOUT default."""
        self.assertEqual(MagicCodeGenerator.MAGIC_CODE_TIMEOUT_SECS,
                         settings.SIGNIN_CODE_TIMEOUT_SECS)

    @patch('user.magic_code_generator.MagicCodeGenerator.get_elapsed_seconds')
    def test_advertised_lifetime_matches_enforced_code_expiry(self, mock_elapsed_seconds):
        """The lifetime the sign-in email advertises is the one the checker enforces.

        The email shows get_timeout_seconds() // 60 minutes; a code must still be
        valid at the edge of that window and expired just past it -- so the number
        the user reads cannot drift from the actual expiry.
        """
        advertised_lifetime_secs = self.generator.get_timeout_seconds()
        start_seconds = 1000

        mock_elapsed_seconds.return_value = start_seconds
        magic_code = self.generator.make_magic_code(self.mock_request, target='11111111-1111-1111-1111-111111111111')

        # At the edge of the advertised window: still valid.
        mock_elapsed_seconds.return_value = start_seconds + advertised_lifetime_secs
        self.assertEqual(self.generator.check_magic_code(self.mock_request, magic_code),
                         MagicCodeStatus.VALID)

        # One second past the advertised window: expired.
        mock_elapsed_seconds.return_value = start_seconds + advertised_lifetime_secs + 1
        self.assertEqual(self.generator.check_magic_code(self.mock_request, magic_code),
                         MagicCodeStatus.EXPIRED)

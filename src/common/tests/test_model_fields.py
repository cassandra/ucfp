"""
Tests for custom Django model fields.
"""
import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase

from common.labeled_enum import LabeledEnum, LabeledEnumField, NullableLabeledEnumField
from common.models import BoundedDecimalField

logging.disable(logging.CRITICAL)


class TestEnum(LabeledEnum):
    """Test enum for field testing."""
    FIRST = ('First Option', 'The first option')
    SECOND = ('Second Option', 'The second option')
    THIRD = ('Third Option', 'The third option')

    @classmethod
    def default(cls):
        return cls.FIRST


class TestModel(models.Model):
    """Test model for LabeledEnumField testing."""
    safe_field = LabeledEnumField(TestEnum)
    strict_field = LabeledEnumField(TestEnum, use_safe_conversion=False)
    nullable_field = NullableLabeledEnumField(TestEnum)

    class Meta:
        app_label = 'common'
        # Don't create database table
        managed = False


class TestLabeledEnumField(TestCase):
    """Test the LabeledEnumField custom field."""

    def test_field_accepts_enum_instance(self):
        """Test that field accepts enum instances."""
        obj = TestModel()
        obj.safe_field = TestEnum.SECOND

        self.assertEqual(obj.safe_field, TestEnum.SECOND)
        self.assertIsInstance(obj.safe_field, TestEnum)

    def test_field_accepts_string_lowercase(self):
        """Test that field accepts lowercase string values."""
        obj = TestModel()
        obj.safe_field = 'second'

        self.assertEqual(obj.safe_field, TestEnum.SECOND)
        self.assertIsInstance(obj.safe_field, TestEnum)

    def test_field_accepts_string_uppercase(self):
        """Test that field accepts uppercase string values."""
        obj = TestModel()
        obj.safe_field = 'THIRD'

        self.assertEqual(obj.safe_field, TestEnum.THIRD)
        self.assertIsInstance(obj.safe_field, TestEnum)

    def test_field_accepts_string_mixed_case(self):
        """Test that field accepts mixed case string values."""
        obj = TestModel()
        obj.safe_field = 'FiRsT'

        self.assertEqual(obj.safe_field, TestEnum.FIRST)
        self.assertIsInstance(obj.safe_field, TestEnum)

    def test_safe_field_handles_invalid_value(self):
        """Test that safe field returns default for invalid values."""
        obj = TestModel()
        obj.safe_field = 'invalid'

        # Should return default (FIRST) for invalid value
        self.assertEqual(obj.safe_field, TestEnum.FIRST)

    def test_strict_field_raises_on_invalid_value(self):
        """Test that strict field raises error for invalid values."""
        obj = TestModel()

        # Setting invalid value should work initially (no validation yet)
        obj.strict_field = 'invalid'

        # But accessing it should raise an error during conversion
        with self.assertRaises(ValidationError) as context:
            # Force conversion by accessing to_python
            field = obj._meta.get_field('strict_field')
            field.to_python('invalid')

        self.assertIn('Invalid value', str(context.exception))

    def test_get_prep_value_returns_lowercase(self):
        """Test that get_prep_value returns lowercase string."""
        field = TestModel._meta.get_field('safe_field')

        # Test with enum instance
        value = field.get_prep_value(TestEnum.SECOND)
        self.assertEqual(value, 'second')

        # Test with uppercase string
        value = field.get_prep_value('THIRD')
        self.assertEqual(value, 'third')

        # Test with mixed case string
        value = field.get_prep_value('FiRsT')
        self.assertEqual(value, 'first')

    def test_nullable_field_accepts_none(self):
        """Test that nullable field accepts None."""
        obj = TestModel()
        obj.nullable_field = None

        self.assertIsNone(obj.nullable_field)

    def test_nullable_field_has_correct_defaults(self):
        """Test that nullable field has null=True and blank=True."""
        field = TestModel._meta.get_field('nullable_field')

        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_field_choices_are_provided_via_formfield(self):
        """Choices are supplied dynamically via formfield(), NOT baked onto the
        model field -- so enum membership can change without a migration."""
        field = TestModel._meta.get_field('safe_field')

        # Not baked onto the model field.
        self.assertFalse(field.choices)

        # But available on the admin/form field, sourced from the enum.
        form_choices = field.formfield().choices
        self.assertIn(('first', 'First Option'), form_choices)
        self.assertIn(('second', 'Second Option'), form_choices)
        self.assertIn(('third', 'Third Option'), form_choices)

    def test_field_default_is_set(self):
        """Test that field default is properly set from enum."""
        field = TestModel._meta.get_field('safe_field')

        # Default should be lowercase string
        self.assertEqual(field.default, 'first')

    def test_from_db_value_converts_to_enum(self):
        """Test that from_db_value converts string to enum."""
        field = TestModel._meta.get_field('safe_field')

        # Simulate database value
        enum_value = field.from_db_value('second', None, None)

        self.assertEqual(enum_value, TestEnum.SECOND)
        self.assertIsInstance(enum_value, TestEnum)

    def test_value_to_string_for_serialization(self):
        """Test that value_to_string returns lowercase string."""
        obj = TestModel()
        obj.safe_field = TestEnum.THIRD

        field = TestModel._meta.get_field('safe_field')
        string_value = field.value_to_string(obj)

        self.assertEqual(string_value, 'third')


class BoundedDecimalTestModel(models.Model):
    """Test model exercising BoundedDecimalField bound variants."""
    non_negative = BoundedDecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0'),
    )
    positive = BoundedDecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0'),
        exclusive_min=True,
    )
    ranged = BoundedDecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('1'),
        max_value=Decimal('5'),
    )
    capped = BoundedDecimalField(
        max_digits=10,
        decimal_places=2,
        max_value=Decimal('5'),
        exclusive_max=True,
    )

    class Meta:
        app_label = 'common'
        # Don't create database table
        managed = False


class TestBoundedDecimalField(TestCase):
    """Test the BoundedDecimalField custom field."""

    def _field(self, name):
        return BoundedDecimalTestModel._meta.get_field(name)

    def test_non_negative_allows_zero_and_positive(self):
        """min_value=0 is inclusive: zero and positive values pass."""
        field = self._field('non_negative')

        field.run_validators(Decimal('0'))
        field.run_validators(Decimal('123.45'))

    def test_non_negative_rejects_negative(self):
        """A value below the inclusive minimum is rejected."""
        field = self._field('non_negative')

        with self.assertRaises(ValidationError):
            field.run_validators(Decimal('-0.01'))

    def test_positive_rejects_zero(self):
        """exclusive_min excludes the limit itself: zero is rejected."""
        field = self._field('positive')

        with self.assertRaises(ValidationError):
            field.run_validators(Decimal('0'))

    def test_positive_allows_smallest_increment(self):
        """A value strictly above zero passes the exclusive minimum."""
        field = self._field('positive')

        field.run_validators(Decimal('0.01'))

    def test_ranged_accepts_inclusive_bounds(self):
        """Both endpoints of an inclusive range pass."""
        field = self._field('ranged')

        field.run_validators(Decimal('1'))
        field.run_validators(Decimal('3'))
        field.run_validators(Decimal('5'))

    def test_ranged_rejects_below_and_above(self):
        """Values outside the inclusive range are rejected on both ends."""
        field = self._field('ranged')

        with self.assertRaises(ValidationError):
            field.run_validators(Decimal('0.99'))
        with self.assertRaises(ValidationError):
            field.run_validators(Decimal('5.01'))

    def test_scale_violation_is_rejected(self):
        """DecimalField's scale check still applies (no silent rounding)."""
        field = self._field('non_negative')

        with self.assertRaises(ValidationError):
            field.run_validators(Decimal('1.234'))

    def test_exclusive_max_rejects_the_limit(self):
        """exclusive_max excludes the limit itself: the maximum is rejected."""
        field = self._field('capped')

        with self.assertRaises(ValidationError):
            field.run_validators(Decimal('5'))

    def test_exclusive_max_allows_below_limit(self):
        """A value strictly below the maximum passes the exclusive bound."""
        field = self._field('capped')

        field.run_validators(Decimal('4.99'))

    def test_deconstruct_round_trips_bounds(self):
        """deconstruct() emits only the bounds that were set, for migrations."""
        field = BoundedDecimalField(
            max_digits=10,
            decimal_places=2,
            min_value=Decimal('0'),
            exclusive_min=True,
        )

        _name, _path, _args, kwargs = field.deconstruct()

        self.assertEqual(kwargs['min_value'], Decimal('0'))
        self.assertTrue(kwargs['exclusive_min'])
        self.assertNotIn('max_value', kwargs)
        self.assertNotIn('exclusive_max', kwargs)

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property


class TimestampedModel( models.Model ):
    """Abstract base adding self-managed creation/update timestamps.

    `created_datetime` is stamped once on insert; `updated_datetime` refreshes on
    every save. Concrete models inherit both without redeclaring them.
    """

    created_datetime = models.DateTimeField(
        'Created',
        auto_now_add = True,
        blank = True,
        db_index = True,
    )
    updated_datetime = models.DateTimeField(
        'Updated',
        auto_now = True,
        blank = True,
    )

    class Meta:
        abstract = True


@deconstructible
class ExclusiveMinValueValidator( MinValueValidator ):
    """Reject values that are not strictly greater than the limit.

    Django's MinValueValidator is inclusive (value >= limit). This variant
    excludes the limit itself, for fields like a conversion rate that must be
    strictly positive.
    """

    message = 'Ensure this value is greater than %(limit_value)s.'

    def compare( self, value, limit ) -> bool:
        return bool( value <= limit )


@deconstructible
class ExclusiveMaxValueValidator( MaxValueValidator ):
    """Reject values that are not strictly less than the limit.

    The upper-bound counterpart to ExclusiveMinValueValidator: Django's
    MaxValueValidator is inclusive (value <= limit); this excludes the limit.
    """

    message = 'Ensure this value is less than %(limit_value)s.'

    def compare( self, value, limit ) -> bool:
        return bool( value >= limit )


class BoundedDecimalField( models.DecimalField ):
    """A DecimalField with optional inclusive/exclusive value bounds.

    DecimalField constrains digit count (max_digits) and scale (decimal_places)
    but not magnitude. This field adds optional lower/upper bounds so callers can
    declare constraints like non-negative (min_value = 0) or strictly positive
    (min_value = 0, exclusive_min = True) once, at the field, rather than
    repeating validator wiring per model.

    Bounds are enforced by validators, which run during full_clean() and form
    validation -- not at the database layer. Where a hard guarantee is required,
    pair the field with a Meta CheckConstraint.
    """

    def __init__( self,
                  *args,
                  min_value     : Decimal = None,
                  max_value     : Decimal = None,
                  exclusive_min : bool    = False,
                  exclusive_max : bool    = False,
                  **kwargs ):
        self.min_value = min_value
        self.max_value = max_value
        self.exclusive_min = exclusive_min
        self.exclusive_max = exclusive_max
        super().__init__( *args, **kwargs )
        return

    @cached_property
    def validators( self ) -> list:
        return [ *super().validators, *self._bound_validators() ]

    def _bound_validators( self ) -> list:
        bound = list()
        if self.min_value is not None:
            if self.exclusive_min:
                bound.append( ExclusiveMinValueValidator( self.min_value ) )
            else:
                bound.append( MinValueValidator( self.min_value ) )
        if self.max_value is not None:
            if self.exclusive_max:
                bound.append( ExclusiveMaxValueValidator( self.max_value ) )
            else:
                bound.append( MaxValueValidator( self.max_value ) )
        return bound

    def deconstruct( self ):
        name, path, args, kwargs = super().deconstruct()
        if self.min_value is not None:
            kwargs['min_value'] = self.min_value
        if self.max_value is not None:
            kwargs['max_value'] = self.max_value
        if self.exclusive_min:
            kwargs['exclusive_min'] = self.exclusive_min
        if self.exclusive_max:
            kwargs['exclusive_max'] = self.exclusive_max
        return name, path, args, kwargs

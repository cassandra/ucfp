import uuid
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


class JsonDocumentModel( TimestampedModel ):
    """Abstract base for a record whose content is a single JSON document.

    Adds a stable external `uuid`, a user-facing `label`, and a `data` JSONField holding the
    whole serialized payload, on top of TimestampedModel's timestamps. Ownership is left to
    the concrete model (it is domain-specific), as is any typed access to `data`: this base
    is dumb storage, while the typed aggregate and its (de)serialization live with the
    owning app.
    """

    uuid = models.UUIDField( default = uuid.uuid4, unique = True, editable = False )
    label = models.CharField( max_length = 255 )
    data = models.JSONField( default = dict )

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


def build_bound_validators( min_value = None, max_value = None,
                            exclusive_min = False, exclusive_max = False ) -> list:
    """The value-bound validators for a numeric field: an optionally-exclusive lower
    and/or upper bound."""
    bound = list()
    if min_value is not None:
        bound.append(
            ExclusiveMinValueValidator( min_value ) if exclusive_min
            else MinValueValidator( min_value ) )
    if max_value is not None:
        bound.append(
            ExclusiveMaxValueValidator( max_value ) if exclusive_max
            else MaxValueValidator( max_value ) )
    return bound


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
        return build_bound_validators(
            self.min_value, self.max_value, self.exclusive_min, self.exclusive_max )

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

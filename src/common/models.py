from django.db import models


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

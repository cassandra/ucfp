from django.contrib import admin

from .models import ProjectionRunRecord, PlanningResultRecord


@admin.register( ProjectionRunRecord )
class ProjectionRunRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    # `data` holds the encrypted captured document (it embeds the profile/plans and
    # figures); keep it out of the admin so the operator debugs runs without decrypting.
    exclude = (
        'data',
    )
    list_display = (
        'label',
        'organization',
        'books',
        'uuid',
        'created_datetime',
    )
    list_filter = (
        'organization',
    )
    search_fields = (
        'label',
        'uuid',
        'organization__name',
    )
    readonly_fields = (
        'uuid',
        'created_datetime',
        'updated_datetime',
    )


@admin.register( PlanningResultRecord )
class PlanningResultRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    # `data` holds the encrypted result document; keep it out of the admin so the
    # operator debugs results without decrypting.
    exclude = (
        'data',
    )
    list_display = (
        'label',
        'feature',
        'organization',
        'run',
        'uuid',
        'created_datetime',
    )
    list_filter = (
        'feature',
        'organization',
    )
    search_fields = (
        'label',
        'uuid',
        'organization__name',
    )
    readonly_fields = (
        'uuid',
        'created_datetime',
        'updated_datetime',
    )

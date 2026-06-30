from django.contrib import admin

from .models import ProfileRecord, PlansRecord, AssumptionsRecord


@admin.register( ProfileRecord )
class ProfileRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'label',
        'organization',
        'effective_date',
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


@admin.register( PlansRecord )
class PlansRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'label',
        'organization',
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


@admin.register( AssumptionsRecord )
class AssumptionsRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'label',
        'organization',
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

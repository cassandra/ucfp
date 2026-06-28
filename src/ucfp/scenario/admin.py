from django.contrib import admin

from .models import ScenarioRecord


@admin.register( ScenarioRecord )
class ScenarioRecordAdmin( admin.ModelAdmin ):
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

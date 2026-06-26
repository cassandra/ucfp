from django.contrib import admin

from .models import ProjectionRunRecord


@admin.register( ProjectionRunRecord )
class ProjectionRunRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

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

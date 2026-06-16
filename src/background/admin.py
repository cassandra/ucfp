from django.contrib import admin

from .locks import DatabaseLock


@admin.register(DatabaseLock)
class DatabaseLockAdmin(admin.ModelAdmin):
    show_full_result_count = False

    list_display = (
        'name',
        'acquired_at',
        'initialized',
    )

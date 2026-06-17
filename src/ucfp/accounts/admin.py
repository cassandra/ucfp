from django.contrib import admin

from .models import Account, Journal, Entry, Transaction


@admin.register( Account )
class AccountAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'name',
        'organization',
        'account_type',
        'parent',
        'currency',
        'closed',
        'system_role',
    )
    list_filter = (
        'account_type',
        'closed',
    )
    search_fields = (
        'name',
        'uuid',
        'organization__name',
    )
    readonly_fields = (
        'uuid',
    )


@admin.register( Journal )
class JournalAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'label',
        'organization',
        'as_of_date',
        'uuid',
        'created_datetime',
    )
    search_fields = (
        'label',
        'uuid',
        'organization__name',
    )
    readonly_fields = (
        'uuid',
    )


@admin.register( Transaction )
class TransactionAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'uuid',
        'journal',
        'transaction_date',
        'currency',
        'description',
    )
    search_fields = (
        'uuid',
        'description',
        'journal__label',
    )
    readonly_fields = (
        'uuid',
    )


@admin.register( Entry )
class EntryAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'uuid',
        'transaction',
        'account',
        'entry_direction',
        'amount',
        'transaction_amount',
    )
    list_filter = (
        'entry_direction',
    )
    search_fields = (
        'uuid',
        'account__name',
    )
    readonly_fields = (
        'uuid',
    )

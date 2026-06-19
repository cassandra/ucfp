from django.contrib import admin

from .models import AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord


@admin.register( AccountRecord )
class AccountRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'name',
        'books',
        'account_type',
        'asset_class',
        'income_tax_class',
        'expense_tax_class',
        'parent',
        'closed',
        'system_role',
    )
    list_filter = (
        'account_type',
        'asset_class',
        'income_tax_class',
        'expense_tax_class',
        'closed',
    )
    search_fields = (
        'name',
        'uuid',
        'books__organization__name',
    )
    readonly_fields = (
        'uuid',
    )


@admin.register( BooksOfAccountRecord )
class BooksOfAccountRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'label',
        'organization',
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


@admin.register( TransactionRecord )
class TransactionRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'uuid',
        'books',
        'transaction_date',
        'description',
    )
    search_fields = (
        'uuid',
        'description',
        'books__label',
    )
    readonly_fields = (
        'uuid',
    )


@admin.register( EntryRecord )
class EntryRecordAdmin( admin.ModelAdmin ):
    show_full_result_count = False

    list_display = (
        'uuid',
        'transaction',
        'account',
        'entry_direction',
        'amount',
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

"""Model signal receivers for the accounts layer.

Registers the fail-safe write-guard for this app's organization-scoped record (see
organization.write_guard): its persistence is refused during a read-only member's request, so a write
riding a GET that the HTTP-method gate cannot see fails toward denied rather than silently changing
shared data.
"""
from organization.write_guard import connect_write_guard

from .models import AccountRecord, BooksOfAccountRecord, EntryRecord, TransactionRecord

# The books record and its child rows (accounts, transactions, entries) all hang off the organization;
# guard each directly rather than relying on the parent's guard tripping first within the save.
connect_write_guard( BooksOfAccountRecord, AccountRecord, TransactionRecord, EntryRecord )

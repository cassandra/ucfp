"""A read-only member may still reshape and drill into the run results table.

The column operations (expand/collapse, hide/show, move) persist only the member's own per-user session
lens (`SessionState.books_table_definition`), never organization data -- so the view opts out of the
read-only write-gate. Without the opt-out the method-gate would 403 the column POSTs and trap a viewer
in a fixed table, losing a core feature. (The gate's honoring of this marker is covered in
organization.tests.test_decorators.)
"""
from django.test import SimpleTestCase

from ucfp.planning.views import ProjectionRunBooksTableView


class BooksTableReadonlyOptOutTest( SimpleTestCase ):

    def test_column_operations_are_exempt_from_the_readonly_write_gate( self ):
        self.assertTrue( ProjectionRunBooksTableView.permits_readonly_mutation )

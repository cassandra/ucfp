"""The acknowledgment fold (#255): a record that acknowledged every old key folded into a current key
counts as having acknowledged the current one, so a re-sectioning does not strand an already-reviewed
record -- and storage still holds only the keys actually acknowledged, never a fold-derived one."""
import unittest

from django.test import SimpleTestCase

from ucfp.inputs.models import AssumptionsRecord


class AcknowledgmentFoldingTests( SimpleTestCase ):

    def test_both_folded_keys_imply_the_current_key( self ):
        record = AssumptionsRecord( acknowledged_sections = [ 'net-worth', 'transaction-costs' ] )
        self.assertIn( 'advanced', record.acknowledged_section_keys )

    def test_a_partial_fold_does_not_imply_the_current_key( self ):
        record = AssumptionsRecord( acknowledged_sections = [ 'transaction-costs' ] )
        self.assertNotIn( 'advanced', record.acknowledged_section_keys )

    def test_the_fold_is_read_only_and_does_not_pollute_storage( self ):
        record = AssumptionsRecord( acknowledged_sections = [ 'net-worth', 'transaction-costs' ] )
        record.acknowledge( 'advanced' )                       # already implied -> a no-op, no save
        self.assertEqual( record.acknowledged_sections, [ 'net-worth', 'transaction-costs' ] )


if __name__ == '__main__':
    unittest.main()

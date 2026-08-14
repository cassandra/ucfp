"""Value-level Profile diff: the household facts that changed between two Profile snapshots, surfaced when
an exploration's runs predate a Profile update."""
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from ucfp.accounts.enums import AssetClass
from ucfp.inputs.profile.schemas import AssetProfile, Debt, Profile, SubjectProfile
from ucfp.inputs.profile.enums import DebtKind
from ucfp.jurisdiction.enums import FilingStatus
from ucfp.planning.profile_diff import profile_changes

_D = Decimal


def _profile( **overrides ) -> Profile:
    base = dict(
        subjects = [ SubjectProfile( handle = 'me', name = 'Me', birthdate = date( 1980, 1, 1 ) ) ],
        filing_status = FilingStatus.SINGLE,
        assets = [
            AssetProfile( handle = 'ira', name = 'IRA', asset_class = AssetClass.PRETAX_RETIREMENT,
                          opening_value = _D( '300000' ), cost_basis = _D( '0' ) ) ],
        debts = [ Debt( handle = 'car', name = 'Car loan', kind = DebtKind.AUTO, balance = _D( '15000' ) ) ] )
    base.update( overrides )
    return Profile( **base )


class ProfileChangesTests( unittest.TestCase ):

    def test_identical_profiles_have_no_changes( self ):
        self.assertEqual( profile_changes( _profile(), _profile() ), [] )

    def test_asset_value_change_is_described_value_to_value( self ):
        after = _profile( assets = [
            AssetProfile( handle = 'ira', name = 'IRA', asset_class = AssetClass.PRETAX_RETIREMENT,
                          opening_value = _D( '320000' ), cost_basis = _D( '0' ) ) ] )
        self.assertEqual( profile_changes( _profile(), after ), [ 'IRA value $300,000 → $320,000' ] )

    def test_added_and_removed_assets( self ):
        after = _profile( assets = [
            AssetProfile( handle = 'brok', name = 'Brokerage', asset_class = AssetClass.STOCKS,
                          opening_value = _D( '50000' ), cost_basis = _D( '40000' ) ) ] )
        changes = profile_changes( _profile(), after )
        self.assertIn( 'Added Brokerage ($50,000)', changes )
        self.assertIn( 'Removed IRA', changes )

    def test_filing_status_and_debt_balance_changes( self ):
        after = _profile(
            filing_status = FilingStatus.MARRIED_JOINT,
            debts = [ Debt( handle = 'car', name = 'Car loan', kind = DebtKind.AUTO,
                            balance = _D( '9000' ) ) ] )
        changes = profile_changes( _profile(), after )
        self.assertIn( 'Filing status Single → Married Filing Jointly', changes )
        self.assertIn( 'Car loan balance $15,000 → $9,000', changes )

    def test_subject_birthdate_change( self ):
        after = replace(
            _profile(),
            subjects = [ SubjectProfile( handle = 'me', name = 'Me', birthdate = date( 1981, 1, 1 ) ) ] )
        self.assertEqual( profile_changes( _profile(), after ), [ 'Me birthdate 1980-01-01 → 1981-01-01' ] )


if __name__ == '__main__':
    unittest.main()

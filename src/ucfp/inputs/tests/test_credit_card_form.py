"""CreditCardPlanForm: the paydown-mode switch's vocabulary comes from CreditCardPlanMode through the
form -- the case strings and each option's readout kind -- so inputs.js and the template carry no mode
member-name literals, and a rename stays consistent (the radio values are the same names). Adding a mode
without a readout kind fails loudly (building the options raises), so the map cannot fall behind.
"""
import unittest
from decimal import Decimal

from django.http import QueryDict
from django.template.loader import render_to_string

from ucfp.environment.constants import AppConst
from ucfp.inputs.credit_card import CreditCardPlanForm, _CARRY
from ucfp.inputs.plans.enums import CreditCardPlanMode
from ucfp.inputs.plans.schemas import Plans
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.profile.schemas import Debt, Profile

_KINDS = {
    AppConst.CARD_READOUT_INTEREST_ONLY, AppConst.CARD_READOUT_CLEARS_BY_PAYMENT,
    AppConst.CARD_READOUT_PAYMENT_FOR_DATE, AppConst.CARD_READOUT_BALANCE_AT_DATE }


def _form() -> CreditCardPlanForm:
    profile = Profile(
        debts = [ Debt( handle = 'c1', name = 'Visa', kind = DebtKind.CREDIT_CARD,
                        balance = Decimal( '5000' ) ) ] )
    return CreditCardPlanForm( profile = profile )


class CreditCardSwitchTokenTests( unittest.TestCase ):

    def test_case_strings_derive_from_the_mode_members( self ):
        form = _form()
        self.assertEqual( form.monthly_field_modes,
                          f'{CreditCardPlanMode.MONTHLY.name} {CreditCardPlanMode.COMBO.name}' )
        self.assertEqual( form.date_field_modes,
                          f'{CreditCardPlanMode.BY_DATE.name} {CreditCardPlanMode.COMBO.name} '
                          f'{CreditCardPlanMode.LUMP.name}' )

    def test_the_radio_values_are_carry_plus_the_member_names( self ):
        # The radios and the case strings both use the member names, so a field shows for exactly the
        # modes that name it -- the invariant that keeps the switch working across a rename.
        values = { option[ 'value' ] for option in _form().rows[ 0 ][ 'mode_options' ] }
        self.assertEqual( values, { _CARRY } | { mode.name for mode in CreditCardPlanMode } )

    def test_every_option_carries_a_known_readout_kind( self ):
        by_value = { option[ 'value' ] : option[ 'kind' ]
                     for option in _form().rows[ 0 ][ 'mode_options' ] }
        self.assertEqual( set( by_value.values() ), _KINDS )                 # only the known kinds
        self.assertEqual( by_value[ _CARRY ], AppConst.CARD_READOUT_INTEREST_ONLY )
        self.assertEqual( by_value[ CreditCardPlanMode.LUMP.name ], AppConst.CARD_READOUT_INTEREST_ONLY )
        self.assertEqual( by_value[ CreditCardPlanMode.MONTHLY.name ], AppConst.CARD_READOUT_CLEARS_BY_PAYMENT )
        self.assertEqual( by_value[ CreditCardPlanMode.COMBO.name ], AppConst.CARD_READOUT_BALANCE_AT_DATE )

    def test_a_fresh_card_defaults_to_carry_checked( self ):
        checked = [ option for option in _form().rows[ 0 ][ 'mode_options' ] if option[ 'checked' ] ]
        self.assertEqual( [ option[ 'value' ] for option in checked ], [ _CARRY ] )

    def test_rendered_options_each_carry_their_kind( self ):
        html = render_to_string( 'inputs/interview/sections/credit_card_list.html',
                                 { 'credit_card_form': _form(), 'AppConst': AppConst } )
        self.assertEqual( html.count( f'data-{AppConst.CARD_MODE_KIND_DATA_ATTR}' ), 5 )   # one per option

    def test_a_submitted_mode_still_round_trips_to_a_plan( self ):
        # The radios are now rendered by hand; confirm their name/value still submit so `apply` builds
        # the plan (the form reads the POST field regardless of how the radio was rendered).
        profile = Profile(
            debts = [ Debt( handle = 'c1', name = 'Visa', kind = DebtKind.CREDIT_CARD,
                            balance = Decimal( '5000' ) ) ] )
        data = QueryDict( mutable = True )
        data.update( { 'mode_c1': CreditCardPlanMode.MONTHLY.name, 'monthly_c1': '200' } )
        form = CreditCardPlanForm( data, profile = profile, plans = Plans() )
        self.assertTrue( form.is_valid(), form.errors )
        _profile, plans = form.apply( profile, Plans() )
        self.assertEqual( plans.credit_card_plans[ 0 ].mode, CreditCardPlanMode.MONTHLY )
        self.assertEqual( plans.credit_card_plans[ 0 ].monthly_payment, Decimal( '200' ) )


if __name__ == '__main__':
    unittest.main()

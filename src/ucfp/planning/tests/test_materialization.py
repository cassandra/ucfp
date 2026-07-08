"""Materialization of property-scoped expenses: the tax-class derivation.

A `PROPERTY` expense flow stores its *personal* tax class (`SALT` for property tax, `LIVING`
otherwise); materialization derives the class the engine sees from the property the flow attaches to
-- a rental's operating cost nets as a `RENTAL_EXPENSE`, while a personal dwelling's (and a household
or rented-home flow, which has no owned asset) keeps its stored personal class. This mirrors the
mortgage-interest derivation tested end-to-end in `ucfp.forecast.tests.test_rental`.
"""
import unittest
from decimal import Decimal

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.parameters import WindowedAmount
from ucfp.inputs.plans.schemas import ExpenseFlow, Plans
from ucfp.inputs.profile.schemas import AssetProfile
from ucfp.parameter_sets.enums import ExpenseCategory
from ucfp.planning.materialization import _plans_expenses


def _property( handle : str, asset_class : AssetClass ) -> AssetProfile:
    return AssetProfile(
        handle = handle, name = handle.title(), asset_class = asset_class,
        opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) )


def _property_tax( handle ) -> ExpenseFlow:
    # A property-tax flow carries its personal class (SALT); the handle picks the property it derives
    # against (None for a household or rented-home flow, which owns no asset).
    return ExpenseFlow(
        name = 'Property Tax', category = ExpenseCategory.PROPERTY,
        expense_tax_class = ExpenseTaxClass.SALT,
        schedule = [ WindowedAmount( Decimal( '6000' ) ) ], property_handle = handle )


class PropertyExpenseTaxClassTests( unittest.TestCase ):

    _ASSETS = { 'residence': _property( 'residence', AssetClass.REAL_ESTATE_RESIDENCE ),
                'second-home': _property( 'second-home', AssetClass.REAL_ESTATE_SECOND_HOME ),
                'rental': _property( 'rental', AssetClass.REAL_ESTATE_RENTAL ) }

    def _materialized_classes( self, *handles ) -> list:
        plans = Plans( expenses = [ _property_tax( handle ) for handle in handles ] )
        streams, _items = _plans_expenses( plans, self._ASSETS )
        return [ stream.expense_tax_class for stream in streams ]

    def test_rental_property_expense_derives_rental_expense( self ):
        # Same stored SALT class on all three; only the rental's derives to a (rent-netting) rental
        # expense. A second home is personal-use like the residence, so its property tax stays SALT --
        # the non-obvious fall-through (it is not netted like a rental).
        residence, second_home, rental = self._materialized_classes(
            'residence', 'second-home', 'rental' )
        self.assertEqual( residence, ExpenseTaxClass.SALT )
        self.assertEqual( second_home, ExpenseTaxClass.SALT )
        self.assertEqual( rental, ExpenseTaxClass.RENTAL_EXPENSE )

    def test_flow_without_an_owned_asset_keeps_its_personal_class( self ):
        # A household flow (no property_handle) and a tenant's rented-home flow (a handle with no owned
        # asset) both fall through to the stored personal class -- never a rental expense.
        household, rented_home = self._materialized_classes( None, 'rent' )
        self.assertEqual( household, ExpenseTaxClass.SALT )
        self.assertEqual( rented_home, ExpenseTaxClass.SALT )

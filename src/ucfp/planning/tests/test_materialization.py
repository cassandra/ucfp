"""Materialization of property operating expenses: the tax-class derivation.

A `PropertyExpense` stores its *personal* tax class (`SALT` for property tax, `LIVING` otherwise);
materialization derives the class the engine sees from the property each shared amount lands on -- a
rental's operating cost nets as a `RENTAL_EXPENSE`, while a personal dwelling's (and a rented-home
flow, which has no owned asset) keeps its stored personal class. This mirrors the mortgage-interest
derivation tested end-to-end in `ucfp.forecast.tests.test_rental`.
"""
import unittest
from decimal import Decimal

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.inputs.plans.schemas import Plans, PropertyExpense
from ucfp.inputs.profile.enums import HousingTenure
from ucfp.inputs.profile.schemas import AssetProfile, Profile
from ucfp.parameter_sets.enums import ExpenseCategory, PropertyContext
from ucfp.planning.materialization import _property_expenses

_OWNED    = ( PropertyContext.RESIDENCE, PropertyContext.SECOND_HOME, PropertyContext.RENTAL )
_OCCUPIED = _OWNED + ( PropertyContext.RENTED_HOME, )


def _property( handle : str, asset_class : AssetClass ) -> AssetProfile:
    return AssetProfile(
        handle = handle, name = handle.title(), asset_class = asset_class,
        opening_value = Decimal( '500000' ), cost_basis = Decimal( '500000' ) )


def _expense( applies_to, tax_class ) -> PropertyExpense:
    # One shared property expense at a flat default, applied to the contexts in `applies_to`.
    return PropertyExpense(
        name = 'Upkeep', category = ExpenseCategory.PROPERTY, expense_tax_class = tax_class,
        applies_to = applies_to, default_amount = Decimal( '6000' ) )


class PropertyExpenseTaxClassTests( unittest.TestCase ):

    def test_rental_property_expense_derives_rental_expense( self ):
        # One SALT property-tax expense applied to every owned dwelling: only the rental's derives to a
        # (rent-netting) rental expense. A second home is personal-use like the residence, so its tax
        # stays SALT -- the non-obvious fall-through (it is not netted like a rental).
        profile = Profile( assets = [
            _property( 'residence', AssetClass.REAL_ESTATE_RESIDENCE ),
            _property( 'second-home', AssetClass.REAL_ESTATE_SECOND_HOME ),
            _property( 'rental', AssetClass.REAL_ESTATE_RENTAL ) ] )
        plans = Plans( property_expenses = [ _expense( _OWNED, ExpenseTaxClass.SALT ) ] )
        streams, _items = _property_expenses(
            profile, plans, { a.handle : a for a in profile.assets }, dict() )
        self.assertEqual(
            [ stream.expense_tax_class for stream in streams ],
            [ ExpenseTaxClass.SALT, ExpenseTaxClass.SALT, ExpenseTaxClass.RENTAL_EXPENSE ] )

    def test_rented_home_flow_keeps_its_personal_class( self ):
        # A tenant's rented home (a handle with no owned asset, present when the tenure is RENT) takes
        # occupied expenses (utilities, rent) and falls through to the stored personal class -- never a
        # rental expense.
        profile = Profile( home_tenure = HousingTenure.RENT )
        plans = Plans( property_expenses = [ _expense( _OCCUPIED, ExpenseTaxClass.LIVING ) ] )
        streams, _items = _property_expenses( profile, plans, dict(), dict() )
        self.assertEqual( [ s.expense_tax_class for s in streams ], [ ExpenseTaxClass.LIVING ] )

"""Plan events (#105): a Transfer's materialization *choice* -- which scheduled event it emits.

The engine already proves each scheduled event behaves correctly (see `forecast/tests/test_events.py`);
what earns a committed test here is the routing decision the inputs layer makes, because it regresses
silently -- a revert to a plain `ScheduledTransfer` for a stock source would make the sale tax-free and
every engine test would still pass. The dispatch keys on the settled `AssetClass` taxonomy, so it is
stable dispatch, not churning model. Only the branch (appreciating vs face-value source) and its
cash-hub-vs-conversion destination sub-rule are pinned here; gain/basis math is the engine's to test.
"""
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from common.recurrence import OneTime
from common.schedule import Schedule

from ucfp.accounts.enums import AssetClass, ExpenseTaxClass
from ucfp.forecast.parameters import (
    ScheduledLoanPayoff, ScheduledRealization, ScheduledTransfer, WindowedAmount )
from ucfp.inputs.events import (
    BoundOption, EventContributions, EventForm, GeneralPaymentEvent, POSSESSION_ROLE, PROPERTY_ROLE,
    PAYMENT_EXPENSE_HANDLE_BASE, SOURCE_ROLE, TARGET_ROLE, SellPossessionEvent, SellPropertyEvent,
    TransferEvent, _payoff_loan_handle, payment_expense_handle, vehicle_disposition_contributions )
from ucfp.inputs.plans.enums import EventKind, VehicleDispositionKind
from ucfp.inputs.plans.schemas import PlanEvent, Plans, Vehicle, VehicleDisposition, VehiclePlan
from ucfp.inputs.profile.enums import DebtKind


def _profile( *holdings ):
    """A minimal stand-in profile: `(handle, asset_class)` pairs a transfer can move between."""
    assets = [ SimpleNamespace( handle = handle, asset_class = klass ) for handle, klass in holdings ]
    return SimpleNamespace( assets = assets )


def _transfer( source, target, amount = Decimal( '50000' ) ):
    return PlanEvent( kind = EventKind.TRANSFER, date = date( 2030, 3, 1 ), amount = amount,
                      selections = { SOURCE_ROLE: source, TARGET_ROLE: target } )


def _materialize( profile, event ):
    into = EventContributions()
    TransferEvent().contribute( event, profile, {}, into )
    return into.scheduled_events


class TransferMaterializationTests( unittest.TestCase ):

    def test_appreciating_source_to_cash_realizes_into_the_cash_hub( self ):
        profile = _profile( ( 'stk', AssetClass.STOCKS ), ( 'cash', AssetClass.CASH ) )
        events  = _materialize( profile, _transfer( 'stk', 'cash' ) )
        self.assertEqual( len( events ), 1 )
        realization = events[ 0 ]
        self.assertIsInstance( realization, ScheduledRealization )
        self.assertEqual( realization.holding, 'stk' )
        self.assertEqual( realization.amount, Decimal( '50000' ) )
        self.assertIsNone( realization.destination )       # proceeds to the cash hub

    def test_appreciating_source_to_holding_is_a_conversion( self ):
        # a non-cash target keeps the destination handle, so the proceeds re-establish basis there
        profile = _profile( ( 'stk', AssetClass.STOCKS ), ( 'roth', AssetClass.ROTH ) )
        events  = _materialize( profile, _transfer( 'stk', 'roth' ) )
        realization = events[ 0 ]
        self.assertIsInstance( realization, ScheduledRealization )
        self.assertEqual( realization.destination, 'roth' )

    def test_face_value_source_stays_a_plain_transfer( self ):
        # a CD (or cash) source carries no embedded gain -- a plain, no-tax value move
        profile = _profile( ( 'cd', AssetClass.CDS ), ( 'stk', AssetClass.STOCKS ) )
        events  = _materialize( profile, _transfer( 'cd', 'stk' ) )
        self.assertEqual( len( events ), 1 )
        transfer = events[ 0 ]
        self.assertIsInstance( transfer, ScheduledTransfer )
        self.assertEqual( ( transfer.source, transfer.target, transfer.amount ),
                          ( 'cd', 'stk', Decimal( '50000' ) ) )


def _debt_stub( handle, secured_asset, name ):
    """A stand-in secured debt: a securing debt in these sale tests is an auto loan (so its payoff resolves
    to the vehicle-scoped account handle); an unsecured one is a card (its kind never routes a payoff)."""
    kind = DebtKind.AUTO if secured_asset is not None else DebtKind.CREDIT_CARD
    return SimpleNamespace( handle = handle, secured_asset = secured_asset, name = name, kind = kind )


def _sale_profile( possessions, debts = () ):
    """A stand-in profile for a possession sale: possessions as (handle, class, name) and any securing
    debts as (handle, secured_asset, name)."""
    return SimpleNamespace(
        assets   = [ SimpleNamespace( handle = h, asset_class = k, name = n ) for h, k, n in possessions ],
        debts    = [ _debt_stub( h, s, n ) for h, s, n in debts ],
        subjects = [] )


def _sell( possession_handle ):
    return PlanEvent( kind = EventKind.SELL_POSSESSION, date = date( 2030, 6, 1 ),
                      selections = { POSSESSION_ROLE: possession_handle } )


def _sale_events( profile, event ):
    into = EventContributions()
    SellPossessionEvent().contribute( event, profile, {}, into )
    return into.scheduled_events


class SellPossessionTests( unittest.TestCase ):
    """A possession sale mirrors a property sale: realize the whole holding at its projected value, and
    pay off any loan secured against it. The routing (whole-holding realization + secured-loan payoff) is
    what regresses silently, so it earns a test here; the gain/tax math is the engine's."""

    def test_a_sale_realizes_the_whole_possession( self ):
        profile     = _sale_profile( [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ] )
        events      = _sale_events( profile, _sell( 'possession-1' ) )
        self.assertEqual( len( events ), 1 )
        realization = events[ 0 ]
        self.assertIsInstance( realization, ScheduledRealization )
        self.assertEqual( realization.holding, 'possession-1' )
        self.assertIsNone( realization.amount )   # None -> the whole holding at its projected value

    def test_a_secured_possession_also_pays_off_its_loan( self ):
        profile = _sale_profile(
            [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ],
            [ ( 'debt-1', 'possession-1', 'Car loan' ) ] )      # secured against the car
        events  = _sale_events( profile, _sell( 'possession-1' ) )
        self.assertEqual( [ type( e ).__name__ for e in events ],
                          [ 'ScheduledRealization', 'ScheduledLoanPayoff' ] )
        self.assertIsInstance( events[ 1 ], ScheduledLoanPayoff )
        # The payoff targets the loan's vehicle-scoped *account* handle, not the Debt's own `{v}-loan`
        # identity -- an auto loan materializes under `vehicle-loan:{v}`.
        self.assertEqual( events[ 1 ].loan, 'vehicle-loan:possession-1' )

    def test_a_sale_records_its_date_for_running_cost_clipping( self ):
        # The sale date is recorded so materialization ends the possession's running costs at it (a sold
        # car stops incurring insurance/fuel), mirroring a property sale's operating-cost clip.
        profile = _sale_profile( [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ] )
        into    = EventContributions()
        SellPossessionEvent().contribute( _sell( 'possession-1' ), profile, {}, into )
        self.assertEqual( into.possession_sales, { 'possession-1' : date( 2030, 6, 1 ) } )

    def test_an_unsecured_possession_emits_only_the_realization( self ):
        profile = _sale_profile(
            [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ],
            [ ( 'debt-1', None, 'Credit card' ) ] )             # a debt not secured against the car
        events  = _sale_events( profile, _sell( 'possession-1' ) )
        self.assertEqual( [ type( e ).__name__ for e in events ], [ 'ScheduledRealization' ] )

    def test_the_summary_names_the_item_and_flags_a_payoff( self ):
        profile = _sale_profile(
            [ ( 'possession-1', AssetClass.DEPRECIATING, 'Car' ) ],
            [ ( 'debt-1', 'possession-1', 'Car loan' ) ] )
        summary = SellPossessionEvent().summary( _sell( 'possession-1' ), profile )
        self.assertIn( 'Sell Car in 2030', summary )
        self.assertIn( 'loan paid off', summary )

    def test_the_summary_degrades_gracefully_when_the_item_was_removed( self ):
        # A sale event whose possession the profile no longer has (drift) reads as a removed item, not the
        # bare "None" a missing name used to print.
        summary = SellPossessionEvent().summary( _sell( 'possession-1' ), _sale_profile( [], [] ) )
        self.assertEqual( summary, 'Sell a removed possession in 2030' )

    def test_the_property_sale_summary_also_degrades_when_the_property_was_removed( self ):
        # The parallel fix for a sold-then-removed property (its role points at a REAL_ESTATE asset gone
        # from the profile) -- "a removed property", not "None".
        event   = PlanEvent( kind = EventKind.SELL_PROPERTY, date = date( 2030, 6, 1 ),
                             selections = { PROPERTY_ROLE: 'property-1' } )
        summary = SellPropertyEvent().summary( event, _sale_profile( [], [] ) )
        self.assertEqual( summary, 'Sell a removed property in 2030' )

    def test_offerable_only_when_a_possession_exists( self ):
        self.assertFalse( SellPossessionEvent().offerable( _sale_profile( [] ) ) )
        self.assertTrue( SellPossessionEvent().offerable(
            _sale_profile( [ ( 'possession-1', AssetClass.COLLECTIBLES, 'Ring' ) ] ) ) )

    def test_a_vehicle_is_not_offerable_here( self ):
        # A vehicle (DEPRECIATING) is sold through its vehicle-plan disposition, not this manual sale, so
        # a household with only a vehicle has nothing to sell here.
        self.assertFalse( SellPossessionEvent().offerable(
            _sale_profile( [ ( 'vehicle-1', AssetClass.DEPRECIATING, 'Car' ) ] ) ) )


class VehicleDispositionTests( unittest.TestCase ):
    """A Sell or Replace disposition derives a sale of that current vehicle on the disposition date -- the
    automated transition, from the stored disposition (no written event). Retain sells nothing, and a
    disposition for a missing vehicle is skipped, so a Profile edit degrades gracefully."""

    @staticmethod
    def _profile( vehicles = (), debts = () ):
        return SimpleNamespace(
            assets   = [ SimpleNamespace( handle = h, asset_class = AssetClass.DEPRECIATING, name = n )
                         for h, n in vehicles ],
            debts    = [ _debt_stub( h, s, n ) for h, s, n in debts ],
            subjects = [] )

    # A REPLACE sells the outgoing vehicle only once it is *complete* (its replacement carries structural
    # terms), so the helper attaches a materializable replacement by default; pass replacement=None for
    # the incomplete case (a chosen Replace still being filled in), which must sell nothing.
    _REPLACEMENT = Vehicle( handle = '', purchase_price = Decimal( '30000' ), recurrence_years = 5 )

    @classmethod
    def _plans( cls, kind = None, when = date( 2030, 1, 1 ), handle = 'vehicle-1',
                replacement = _REPLACEMENT ):
        dispositions = ( [ VehicleDisposition( vehicle_handle = handle, kind = kind, sale_date = when,
                                               replacement = replacement ) ]
                         if kind is not None else [] )
        return Plans( vehicle_plan = VehiclePlan( dispositions = dispositions ) )

    def _derive( self, profile, plans ):
        into = EventContributions()
        vehicle_disposition_contributions( profile, plans, into )
        return into

    def test_a_sell_disposition_sells_its_vehicle_on_the_date( self ):
        into = self._derive( self._profile( [ ( 'vehicle-1', 'Old car' ) ] ),
                             self._plans( kind = VehicleDispositionKind.SELL ) )
        self.assertEqual( into.possession_sales, { 'vehicle-1' : date( 2030, 1, 1 ) } )
        self.assertEqual( [ type( e ).__name__ for e in into.scheduled_events ], [ 'ScheduledRealization' ] )
        self.assertEqual( into.scheduled_events[ 0 ].holding, 'vehicle-1' )

    def test_a_replace_disposition_also_sells_the_outgoing_vehicle( self ):
        into = self._derive( self._profile( [ ( 'vehicle-1', 'Old car' ) ] ),
                             self._plans( kind = VehicleDispositionKind.REPLACE ) )
        self.assertEqual( into.possession_sales, { 'vehicle-1' : date( 2030, 1, 1 ) } )

    def test_an_incomplete_replace_sells_nothing( self ):
        # A Replace with a date but no filled-in replacement is incomplete: it must not strand the
        # vehicle (sold with nothing replacing it). It stays retained until the replacement is entered.
        into = self._derive(
            self._profile( [ ( 'vehicle-1', 'Old car' ) ] ),
            self._plans( kind = VehicleDispositionKind.REPLACE, replacement = None ) )
        self.assertEqual( ( into.possession_sales, into.scheduled_events ), ( {}, [] ) )

    def test_a_secured_vehicles_loan_is_paid_off_too( self ):
        into = self._derive(
            self._profile( [ ( 'vehicle-1', 'Old car' ) ], [ ( 'debt-1', 'vehicle-1', 'Loan' ) ] ),
            self._plans( kind = VehicleDispositionKind.SELL ) )
        self.assertEqual( [ type( e ).__name__ for e in into.scheduled_events ],
                          [ 'ScheduledRealization', 'ScheduledLoanPayoff' ] )
        self.assertEqual( into.scheduled_events[ 1 ].loan, 'vehicle-loan:vehicle-1' )   # vehicle-scoped

    def test_retain_derives_nothing( self ):
        into = self._derive( self._profile( [ ( 'vehicle-1', 'Old car' ) ] ),
                             self._plans( kind = VehicleDispositionKind.KEEP ) )
        self.assertEqual( ( into.possession_sales, into.scheduled_events ), ( {}, [] ) )

    def test_no_disposition_derives_nothing( self ):
        into = self._derive( self._profile( [ ( 'vehicle-1', 'Old car' ) ] ), self._plans( kind = None ) )
        self.assertEqual( ( into.possession_sales, into.scheduled_events ), ( {}, [] ) )

    def test_a_disposition_for_a_removed_vehicle_is_skipped( self ):
        # Profile-change robustness: the vehicle is gone, so the disposition derives nothing (no crash).
        into = self._derive( self._profile( [] ), self._plans( kind = VehicleDispositionKind.SELL ) )
        self.assertEqual( ( into.possession_sales, into.scheduled_events ), ( {}, [] ) )


class PayoffLoanHandleTests( unittest.TestCase ):
    """A loan-payoff event resolves its debt to the *account* handle the loan materializes under -- so a
    vehicle auto loan's payoff (from the Debt plan) targets `vehicle-loan:{v}`, not the `{v}-loan` fact."""

    def test_a_vehicle_loan_payoff_targets_the_vehicle_scoped_account( self ):
        profile = SimpleNamespace( debts = [ _debt_stub( 'vehicle-1-loan', 'vehicle-1', 'Car loan' ) ] )
        self.assertEqual( _payoff_loan_handle( profile, 'vehicle-1-loan' ), 'vehicle-loan:vehicle-1' )

    def test_a_non_vehicle_loan_payoff_keeps_the_debt_handle( self ):
        mortgage = SimpleNamespace( handle = 'debt-1', secured_asset = 'property-1', name = 'Mortgage',
                                    kind = DebtKind.MORTGAGE )
        self.assertEqual( _payoff_loan_handle( SimpleNamespace( debts = [ mortgage ] ), 'debt-1' ), 'debt-1' )

    def test_an_unknown_debt_handle_passes_through( self ):
        self.assertEqual( _payoff_loan_handle( SimpleNamespace( debts = [] ), 'gone' ), 'gone' )


def _payment( amount = Decimal( '40000' ), label = '', when = date( 2030, 8, 1 ) ):
    return PlanEvent( kind = EventKind.GENERAL_PAYMENT, date = when, amount = amount, label = label )


def _payment_items( event ):
    into = EventContributions()
    GeneralPaymentEvent().contribute( event, SimpleNamespace(), {}, into )
    return into


class GeneralPaymentMaterializationTests( unittest.TestCase ):
    """A Payment now books as a visible LIVING expense, not an equity disbursement (#210 Phase 1). The
    routing decision -- an `ExpenseItem` named by the payment's label, so the money shows in the expense
    column and same-label payments collapse into one account -- is what regresses silently, so it earns a
    test here; the expense's booking and tax treatment are the engine's to prove."""

    def test_a_payment_is_a_living_expense_item_not_a_disbursement( self ):
        into = _payment_items( _payment( label = 'College Tuition' ) )
        self.assertEqual( into.scheduled_events, [] )     # no longer an equity disbursement
        self.assertEqual( len( into.expense_items ), 1 )
        item = into.expense_items[ 0 ]
        self.assertEqual( item.name, 'College Tuition' )
        self.assertEqual( item.expense_tax_class, ExpenseTaxClass.LIVING )
        self.assertEqual( item.cadence, OneTime( date( 2030, 8, 1 ) ) )
        self.assertEqual( item.amounts, Schedule.constant( WindowedAmount( Decimal( '40000' ) ) ) )
        self.assertEqual( item.handle, 'payment:college-tuition' )

    def test_a_blank_label_falls_back_to_the_default_name( self ):
        item = _payment_items( _payment( label = '' ) ).expense_items[ 0 ]
        self.assertEqual( item.name, 'Payment' )
        self.assertEqual( item.handle, f'{PAYMENT_EXPENSE_HANDLE_BASE}:payment' )

    def test_same_label_payments_share_one_account_key( self ):
        # Same label -> same name and handle, so `ExpenseAccounts` dedups them into one run-table line
        # across years; distinct labels get distinct accounts.
        first  = _payment_items( _payment( label = 'College Tuition', when = date( 2030, 8, 1 ) ) )
        second = _payment_items( _payment( label = 'College Tuition', when = date( 2031, 8, 1 ) ) )
        other  = _payment_items( _payment( label = 'Wedding' ) )
        self.assertEqual( first.expense_items[ 0 ].handle, second.expense_items[ 0 ].handle )
        self.assertNotEqual( first.expense_items[ 0 ].handle, other.expense_items[ 0 ].handle )

    def test_the_handle_helper_slugs_the_label( self ):
        self.assertEqual( payment_expense_handle( 'College Tuition' ), 'payment:college-tuition' )

    def test_the_summary_shows_the_label_amount_and_year( self ):
        summary = GeneralPaymentEvent().summary( _payment( label = 'College Tuition' ), SimpleNamespace() )
        self.assertEqual( summary, 'College Tuition of $40,000 in 2030' )

    def test_the_summary_uses_the_default_name_when_unlabeled( self ):
        self.assertEqual(
            GeneralPaymentEvent().summary( _payment( label = '' ), SimpleNamespace() ),
            'Payment of $40,000 in 2030' )


class GeneralPaymentFormTests( unittest.TestCase ):
    """The Payment add form carries an optional purpose that becomes the event's label; blank yields an
    empty label (the handler then falls back to the default name)."""

    def _built( self, data ):
        form = EventForm( data, event_type = GeneralPaymentEvent(), profile = SimpleNamespace() )
        self.assertTrue( form.is_valid(), form.errors )
        return form.build_event()

    def test_a_purpose_becomes_the_event_label( self ):
        event = self._built( { 'amount': '40000', 'date': '2030-08-01', 'label': '  College Tuition  ' } )
        self.assertEqual( event.label, 'College Tuition' )      # trimmed
        self.assertEqual( event.kind, EventKind.GENERAL_PAYMENT )

    def test_a_blank_purpose_leaves_the_label_empty( self ):
        event = self._built( { 'amount': '40000', 'date': '2030-08-01' } )
        self.assertEqual( event.label, '' )


class SellPropertyOptionFormTests( unittest.TestCase ):
    """The 'Sell a property' add form exposes the residence gate the client reads to show the rent-after
    option only for a primary-residence sale: the profile's residence handle(s) and which option field is
    residence-gated. The gate is offered only to a household that owns a residence, so a rental-only
    profile exposes neither the option nor a handle -- what would otherwise let the client mark a form with
    no option to reveal."""

    @staticmethod
    def _profile( *assets ):
        """A stand-in profile from `(handle, asset_class, name)` real-estate holdings."""
        return SimpleNamespace(
            assets = [ SimpleNamespace( handle = h, asset_class = k, name = n ) for h, k, n in assets ] )

    def _form( self, profile ):
        return EventForm( event_type = SellPropertyEvent(), profile = profile )

    def test_residence_handles_are_only_the_residence_holdings( self ):
        # A residence is the gated option's target; a second home or rental is not, so only the residence
        # handle rides to the client (at most one, but returned as a list).
        profile = self._profile(
            ( 'residence', AssetClass.REAL_ESTATE_RESIDENCE, 'Home' ),
            ( 'property-1', AssetClass.REAL_ESTATE_RENTAL, 'Duplex' ),
            ( 'property-2', AssetClass.REAL_ESTATE_SECOND_HOME, 'Cabin' ) )
        self.assertEqual( self._form( profile ).residence_handles, [ 'residence' ] )

    def test_a_residence_owning_profile_gates_a_residence_only_option( self ):
        profile = self._profile( ( 'residence', AssetClass.REAL_ESTATE_RESIDENCE, 'Home' ) )
        form    = self._form( profile )
        self.assertTrue( form.gates_residence_option )
        options = form.option_fields
        self.assertEqual( len( options ), 1 )
        self.assertIsInstance( options[ 0 ], BoundOption )
        self.assertTrue( options[ 0 ].requires_residence )
        self.assertEqual( options[ 0 ].field.name, 'option_rent_after' )

    def test_a_residence_less_profile_offers_no_gated_option_and_no_handles( self ):
        # Only a rental: the property is sellable, but selling it never makes the household a renter, so
        # there is no rent-after option to gate and no residence handle to mark the form with.
        profile = self._profile( ( 'property-1', AssetClass.REAL_ESTATE_RENTAL, 'Duplex' ) )
        form    = self._form( profile )
        self.assertFalse( form.gates_residence_option )
        self.assertEqual( form.option_fields, [] )
        self.assertEqual( form.residence_handles, [] )


if __name__ == '__main__':
    unittest.main()

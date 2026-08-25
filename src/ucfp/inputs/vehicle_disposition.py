"""The per-current-vehicle disposition editor of the Vehicle plan step.

The vehicle plan is Profile-driven, mirroring the Debt plan: it solicits, for each current vehicle the
household owns (the DEPRECIATING holdings the Vehicles section entered), what to do with it -- Retain it
(the default -- hold it to the end of its life), Sell it on a date, or Replace it on a date with a
recurring purchase. Each choice is a `VehicleDisposition` keyed to the current vehicle's handle; Retain
is stored as the absence of one (so an untouched vehicle is never dangling). A Replace's successor reuses
the shared vehicle-purchase fields (`VehiclePurchaseForm`); net-new future vehicles are a separate list
(`vehicle.py`). This module owns listing the current vehicles and editing one's disposition.
"""
from dataclasses import replace

from django import forms

from common.forms import MoneyField
from common.loan_solver import monthly_payment, resolved_annual_rate
from common.rate import Rate
from common.recurrence import Duration, TimeUnit

from ucfp.accounts.enums import AssetClass
from ucfp.environment.constants import AppConst
from ucfp.inputs.compatibility import snapshot_of
from ucfp.inputs.loan_fieldset import (
    loan_payment_field, loan_rate_field, loan_term_field, seeded_repayment_terms )
from ucfp.inputs.plans.enums import LeaseDispositionKind, PaymentMethod, VehicleDispositionKind
from ucfp.inputs.plans.schemas import (
    LeasedVehicleDisposition, LoanRepayment, Plans, Vehicle, VehicleDisposition, VehiclePlan )
from ucfp.inputs.profile.enums import DebtKind
from ucfp.inputs.vehicle import VehiclePurchaseForm
from ucfp.inputs.vehicle_expenses import plan_has_content, vehicle_plan_of
from ucfp.inputs.vehicle_handles import loan_debt_handle
from ucfp.inputs.widgets import IsoDateInput


def _current_vehicles( profile ) -> list:
    """The household's current vehicles -- the DEPRECIATING holdings the Vehicles (Profile) section
    entered, the entities the disposition list is driven by."""
    if profile is None:
        return list()
    return [ asset for asset in profile.assets if asset.asset_class is AssetClass.DEPRECIATING ]


def _disposition_for( plans, handle : str ):
    """The stored disposition for a current vehicle, or None (meaning Retain -- the default)."""
    plan = vehicle_plan_of( plans )
    if plan is None:
        return None
    return next( ( d for d in plan.dispositions if d.vehicle_handle == handle ), None )


def _vehicle_repayment( plans, handle : str ):
    """The stored `LoanRepayment` for a current vehicle's auto loan -- keyed by its `{v}-loan` debt handle
    -- or None. The loan's terms live in Plans (re-homed here from the Debt plan), the balance in Profile."""
    if plans is None:
        return None
    debt_handle = loan_debt_handle( handle )
    return next( ( r for r in plans.loan_repayments if r.debt_handle == debt_handle ), None )


def dispositions_context( profile, plans ) -> list:
    """One row per current vehicle for the disposition list -- its handle, name, a summary of its current
    disposition (Retain by default), whether that disposition is incomplete (a chosen plan still missing
    structural fields), and a `loan` line for a financed vehicle (its terms, or a prompt to set them)."""
    return [ _disposition_row( asset, _disposition_for( plans, asset.handle ),
                               _loan_summary( profile, plans, asset.handle ) )
             for asset in _current_vehicles( profile ) ]


def _disposition_row( asset, disposition, loan ) -> dict:
    """One current owned vehicle's list row -- its identity, disposition summary, incompleteness (a Retain,
    stored as no disposition, is complete by definition, so it never flags), and its loan status."""
    return { 'handle' : asset.handle, 'name' : asset.name,
             'summary' : _summary( disposition ),
             'incomplete' : disposition is not None and not disposition.is_complete,
             'loan' : loan }


def _loan_summary( profile, plans, handle : str ):
    """A current financed vehicle's loan status for its list row -- its rate and remaining term when set, a
    prompt when not (so a retained financed car is not silently missed), or None when it carries no auto
    loan. Its terms live behind the row's editor; this surfaces them so the row prompts when unset."""
    financed = any( d.kind is DebtKind.AUTO and d.secured_asset == handle for d in profile.debts )
    if not financed:
        return None
    repayment = _vehicle_repayment( plans, handle )
    if repayment is None:
        return 'Loan terms not set'
    percent   = repayment.interest_rate.fraction * 100
    rate_text = f'{percent:.2f}'.rstrip( '0' ).rstrip( '.' )     # trim trailing zeros: 5.00 -> 5, 5.50 -> 5.5
    return f'Loan: {rate_text}%, {repayment.remaining_term.months()} mo left'


def _summary( disposition ) -> str:
    """A current vehicle's disposition in a phrase -- 'Retain' when none is stored, else the kind and, if
    dated, the year it happens."""
    if disposition is None:
        return VehicleDispositionKind.KEEP.label                 # 'Retain'
    if disposition.sale_date is None:
        return disposition.kind.label
    return f'{disposition.kind.label} in {disposition.sale_date.year}'


def _apply_disposition( plans, handle : str, list_field : str, disposition ) -> Plans:
    """Upsert one keyed disposition into the vehicle plan's `list_field` (its owned `dispositions` or
    `leased_dispositions`): replace any disposition for `handle` with `disposition`, or drop it when
    `disposition` is None (the default is stored as absence), then collapse an emptied plan back to None.
    The shared write behind both disposition forms' `apply` -- they differ only in which list and how the
    disposition is built."""
    plan   = vehicle_plan_of( plans ) or VehiclePlan()
    others = [ d for d in getattr( plan, list_field ) if d.vehicle_handle != handle ]
    kept   = others + ( [ disposition ] if disposition is not None else [] )
    plan   = replace( plan, **{ list_field : kept } )
    return replace( plans, vehicle_plan = plan if plan_has_content( plan ) else None )


class VehicleDispositionForm( VehiclePurchaseForm ):
    """The disposition editor for one current vehicle: Retain it (the default), Sell it on a date, or
    Replace it on a date with a recurring purchase (whose fields are the inherited vehicle-purchase ones).
    Keyed to the current vehicle by `handle`. Non-blocking and background-saved: the chosen kind is
    recorded immediately (Retain stores nothing -- it is the default), and materialization emits the sale
    and the replacement only once their date and fields are set. The `kind` radio is the outer switch that
    reveals the date (Sell/Replace) and the replacement fields (Replace); the payment method is a nested
    switch within."""

    kind = forms.ChoiceField(
        label = 'Plan for this vehicle', required = False,
        choices = [ ( k.name, k.label ) for k in VehicleDispositionKind ],
        initial = VehicleDispositionKind.KEEP.name,
        widget = forms.RadioSelect(
            attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
    sale_date = forms.DateField( label = 'Sell or replace on', required = False, widget = IsoDateInput() )
    # The current loan (an owned, financed vehicle only): its planned repayment terms. Rate and monthly are
    # two views of one amortization over `loan_months` (the rate is stored; the monthly is a no-JS
    # back-solve). Shown only when financed; the rate/term seed from the Profile contract facts until a
    # repayment is saved (no invented default -- we never fabricate contract terms). These are the shared
    # loan-terms fields; the client solver (inputs.js) and `common.loan_solver` own the fuller contract.
    loan_rate    = loan_rate_field( hint_id = 'current-loan-hint' )
    loan_monthly = loan_payment_field()
    loan_months  = loan_term_field()

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        self._handle  = handle
        self._profile = profile
        super().__init__( data, initial = self._initial( plans ) if handle else None )

    def _auto_debt( self ):
        """This vehicle's auto-loan `Debt`, or None when it is not financed -- the current loan the card
        edits (a `DEPRECIATING` vehicle carrying an `AUTO` debt secured against it)."""
        debts = self._profile.debts if self._profile is not None else []
        return next( ( d for d in debts if d.kind is DebtKind.AUTO and d.secured_asset == self._handle ),
                     None )

    @property
    def is_financed( self ) -> bool:
        """Whether the vehicle carries an auto loan -- the card shows the current-loan subsection then."""
        return self._auto_debt() is not None

    @property
    def loan_balance( self ):
        """The current loan's outstanding balance -- a Profile fact (the `AUTO` `Debt`'s balance), shown
        read-only in the card and carried to the client calculator; None when the vehicle is not financed."""
        debt = self._auto_debt()
        return debt.balance if debt is not None else None

    def _initial( self, plans ) -> dict:
        disposition = _disposition_for( plans, self._handle )
        initial = { 'kind' : disposition.kind.name if disposition is not None
                    else VehicleDispositionKind.KEEP.name }              # default Retain
        if disposition is not None:
            initial[ 'sale_date' ] = disposition.sale_date
            car = disposition.replacement
            if car is not None:
                initial.update( {
                    'purchase_price' : car.purchase_price, 'recurrence_years' : car.recurrence_years,
                    'end_date' : car.end_date, 'payment_method' : car.payment_method.name,
                    'down_payment' : car.down_payment, 'monthly_payment' : car.monthly_payment,
                    'lease_end_payment' : car.lease_end_payment } )
        # Seed the current loan's rate/term from the stored repayment once it exists, else from the Profile
        # contract facts (the auto `Debt`'s terms); nothing is invented when neither is set.
        rate, term = seeded_repayment_terms( self._auto_debt(), _vehicle_repayment( plans, self._handle ) )
        if term is not None:
            months = term.months()
            initial[ 'loan_months' ] = months
            if rate is not None:
                initial[ 'loan_rate' ] = rate.fraction * 100
                balance = self.loan_balance
                if balance is not None and balance > 0:                 # show the implied monthly too
                    initial[ 'loan_monthly' ] = round( monthly_payment( balance, rate, months ) )
        return initial

    # The kind-switch case values, so the template carries no member-name literals (mirrors the payment
    # switch's `payment_field_methods` etc.).
    @property
    def dated_kinds( self ) -> str:
        """The kinds that need a handover date -- Sell and Replace (Retain needs none)."""
        return f'{VehicleDispositionKind.SELL.name} {VehicleDispositionKind.REPLACE.name}'

    @property
    def replace_kind( self ) -> str:
        """The one kind that buys a replacement -- its case value reveals the replacement fields."""
        return VehicleDispositionKind.REPLACE.name

    def apply( self, profile, plans ):
        kind = VehicleDispositionKind[ self.cleaned_data.get( 'kind' ) or VehicleDispositionKind.KEEP.name ]
        disposition = self._disposition( kind, self.cleaned_data )
        plans = _apply_disposition( plans, self._handle, 'dispositions', disposition )
        return profile, self._apply_loan_terms( plans )

    def _apply_loan_terms( self, plans ) -> Plans:
        """Upsert (or clear) this vehicle's auto-loan repayment from the current-loan fields -- the terms
        re-homed from the Debt plan. A non-financed vehicle, or a term that resolves no rate, stores none;
        keyed by the `{v}-loan` debt handle, leaving other debts' repayments intact."""
        if not self.is_financed:
            return plans
        debt_handle = loan_debt_handle( self._handle )
        others_r    = [ r for r in plans.loan_repayments if r.debt_handle != debt_handle ]
        others_s    = [ s for s in plans.loan_terms_snapshots if s.debt_handle != debt_handle ]
        months      = self.cleaned_data.get( 'loan_months' )
        rate        = self._resolved_rate( months ) if months is not None else None
        if rate is None:                    # incomplete -> no repayment, so no snapshot either
            return replace( plans, loan_repayments = others_r, loan_terms_snapshots = others_s )
        repayment = LoanRepayment( debt_handle = debt_handle, interest_rate = rate,
                                   remaining_term = Duration( months, TimeUnit.MONTH ) )
        # Preserve the seed-time snapshot (the contract when this repayment was established), else record
        # the current Profile terms as the new snapshot.
        existing = next( ( s for s in plans.loan_terms_snapshots if s.debt_handle == debt_handle ), None )
        snapshot = existing if existing is not None else snapshot_of( debt_handle, self._auto_debt().terms )
        return replace( plans, loan_repayments = others_r + [ repayment ],
                        loan_terms_snapshots = others_s + [ snapshot ] )

    def _resolved_rate( self, months : int ):
        """The loan's annual rate from the current-loan fields: the entered `loan_rate` (which the client
        keeps authoritative -- it fills it from an edited monthly), or, as a no-JS fallback, back-solved
        from the monthly payment over the balance and `months`. None when neither determines a rate. The
        entered-vs-back-solved resolution and its plausibility guard live in `common.loan_solver`."""
        entered = self.cleaned_data.get( 'loan_rate' )
        return resolved_annual_rate(
            Rate.percent( entered ) if entered is not None else None,
            self.loan_balance, self.cleaned_data.get( 'loan_monthly' ), months )

    def _disposition( self, kind, cleaned ):
        # Retain is the default, so it is stored as the absence of a disposition (nothing to persist).
        if kind is VehicleDispositionKind.KEEP:
            return None
        replacement = self._replacement( cleaned ) if kind is VehicleDispositionKind.REPLACE else None
        return VehicleDisposition( vehicle_handle = self._handle, kind = kind,
                                   sale_date = cleaned.get( 'sale_date' ), replacement = replacement )

    def _replacement( self, cleaned ) -> Vehicle:
        # The successor's identity and first-purchase date are supplied at materialization from the
        # disposition (handle derived from the current vehicle, purchase date the handover date), so they
        # are left unset here; the name carries the current vehicle's for the run table.
        return Vehicle( handle = '', name = self._current_name(), purchase_date = None,
                        **self._purchase_spec( cleaned ) )

    def _current_name( self ) -> str:
        asset = next( ( a for a in _current_vehicles( self._profile ) if a.handle == self._handle ), None )
        return asset.name if asset is not None else ''


# --- Leased vehicles ------------------------------------------------------

def _leased_disposition_for( plans, handle : str ):
    """The stored leased disposition for a current lease, or None (meaning the default -- Return)."""
    plan = vehicle_plan_of( plans )
    if plan is None:
        return None
    return next( ( d for d in plan.leased_dispositions if d.vehicle_handle == handle ), None )


def leased_dispositions_context( profile, plans ) -> list:
    """One row per current leased vehicle for the disposition list -- its handle, name, a summary of its
    end-of-term plan (Return by default), and whether that plan is incomplete (missing structural
    fields, so it does not yet affect the projection)."""
    leased = profile.leased_vehicles if profile is not None else list()
    return [ _leased_row( vehicle, _leased_disposition_for( plans, vehicle.handle ) )
             for vehicle in leased ]


def _leased_row( vehicle, disposition ) -> dict:
    """One current leased vehicle's list row -- its identity, end-of-term summary, and incompleteness. A
    leased vehicle contributes nothing until its current lease is described (a monthly and an end), so an
    unconfigured lease -- no disposition at all, or an incomplete one -- is flagged, unlike an owned
    vehicle whose Retain default runs it to end-of-life at no extra input. So it is not silently free."""
    return { 'handle' : vehicle.handle, 'name' : vehicle.name,
             'summary' : _leased_summary( disposition ),
             'incomplete' : disposition is None or not disposition.is_complete }


def _leased_summary( disposition ) -> str:
    """A leased vehicle's plan in a phrase -- 'Return' when none is stored, else the kind and, if dated,
    the year the lease ends."""
    if disposition is None:
        return LeaseDispositionKind.RETURN.label                 # 'Return'
    if disposition.lease_end is None:
        return disposition.kind.label
    return f'{disposition.kind.label} in {disposition.lease_end.year}'


def all_dispositions_context( profile, plans ) -> list:
    """One row per current vehicle -- owned then leased -- for the single disposition list: each with its
    handle, name, ownership label, disposition summary, and the edit route its Edit opens (the owned and
    leased editors are separate but share one form area)."""
    owned = [ { **row, 'ownership': 'Owned', 'edit_route': 'vehicle_disposition_edit' }
              for row in dispositions_context( profile, plans ) ]
    leased = [ { **row, 'ownership': 'Leased', 'edit_route': 'leased_disposition_edit' }
               for row in leased_dispositions_context( profile, plans ) ]
    return owned + leased


# Each end-of-term kind fixes what the successor is paid with -- the lease/purchase choice *is* the kind,
# so there is no separate payment picker (unlike an owned Replace). Return has no successor.
_SUCCESSOR_METHOD = {
    LeaseDispositionKind.RENEW    : PaymentMethod.LEASE,
    LeaseDispositionKind.BUY_CASH : PaymentMethod.CASH,
    LeaseDispositionKind.BUY_LOAN : PaymentMethod.LOAN,
}


class LeasedVehicleDispositionForm( VehiclePurchaseForm ):
    """The disposition editor for one current leased vehicle: its current lease terms (monthly, end) and
    what happens at term end -- Return (let it expire), Renew (sign a new lease), Buy with cash, or Buy
    with loan. The kind fixes the successor's payment type, so there is no payment switch (the leased twin
    of an owned Replace's switch): the `kind` radio reveals only the fields its choice needs -- a renewed
    lease's terms, or a purchase's price and financing -- reusing the inherited vehicle-purchase fields
    with conditional labels. Keyed to the leased vehicle by `handle`. Non-blocking and background-saved: a
    bare Return stores nothing (the default); the lease and its successor materialize once set."""

    kind = forms.ChoiceField(
        label = 'At lease end', required = False,
        choices = [ ( k.name, k.label ) for k in LeaseDispositionKind ],
        initial = LeaseDispositionKind.RETURN.name,
        widget = forms.RadioSelect(
            attrs = { 'class' : f'{AppConst.SWITCH_CONTROL_CLASS} form-check-input' } ) )
    monthly   = MoneyField( label = 'Monthly lease payment', min_value = 0, required = False )
    lease_end = forms.DateField( label = 'Lease ends', required = False, widget = IsoDateInput() )

    def __init__( self, data = None, *, profile = None, plans = None, handle = None ):
        self._handle  = handle
        self._profile = profile
        super().__init__( data, initial = self._initial( plans, handle ) if handle else None )

    @staticmethod
    def _initial( plans, handle : str ) -> dict:
        disposition = _leased_disposition_for( plans, handle )
        if disposition is None:
            return { 'kind' : LeaseDispositionKind.RETURN.name }   # default Return
        initial = { 'kind' : disposition.kind.name, 'monthly' : disposition.monthly,
                    'lease_end' : disposition.lease_end }
        car = disposition.successor
        if car is not None:
            initial.update( {
                'purchase_price' : car.purchase_price, 'recurrence_years' : car.recurrence_years,
                'end_date' : car.end_date, 'down_payment' : car.down_payment,
                'monthly_payment' : car.monthly_payment, 'lease_end_payment' : car.lease_end_payment } )
        return initial

    # The kind-switch case values, so the template carries no member-name literals. A field appears once,
    # shown for every kind it applies to (with conditional labels where its meaning differs by kind).
    @property
    def successor_kinds( self ) -> str:
        """The kinds that carry a successor -- everything but Return (they show the recurrence and end)."""
        return ' '.join( k.name for k in _SUCCESSOR_METHOD )

    @property
    def renew_kind( self ) -> str:
        """Renew's case value -- reveals the lease-only fields (its lease-end/turn-in payment)."""
        return LeaseDispositionKind.RENEW.name

    @property
    def buy_kinds( self ) -> str:
        """The buy kinds -- they show the purchase price (a renewed lease has none)."""
        return f'{LeaseDispositionKind.BUY_CASH.name} {LeaseDispositionKind.BUY_LOAN.name}'

    @property
    def financed_kinds( self ) -> str:
        """The kinds with a down and monthly -- a renewed lease (due at signing + monthly) and a loan buy
        (down + monthly). Their labels differ by kind, so the template spans them conditionally."""
        return f'{LeaseDispositionKind.RENEW.name} {LeaseDispositionKind.BUY_LOAN.name}'

    @property
    def buy_loan_kind( self ) -> str:
        """The financed buy -- marked so the auto-loan calculator fills its monthly, and its own labels."""
        return LeaseDispositionKind.BUY_LOAN.name

    def apply( self, profile, plans ):
        kind = LeaseDispositionKind[ self.cleaned_data.get( 'kind' ) or LeaseDispositionKind.RETURN.name ]
        disposition = self._disposition( kind, self.cleaned_data )
        return profile, _apply_disposition( plans, self._handle, 'leased_dispositions', disposition )

    def _disposition( self, kind, cleaned ):
        # A bare Return (the default, no terms entered) stores nothing; any chosen kind or entered lease
        # term is recorded so the current lease's cost (and successor) can materialize.
        monthly, lease_end = cleaned.get( 'monthly' ), cleaned.get( 'lease_end' )
        if kind is LeaseDispositionKind.RETURN and monthly is None and lease_end is None:
            return None
        successor = self._successor( kind, cleaned ) if kind in _SUCCESSOR_METHOD else None
        return LeasedVehicleDisposition( vehicle_handle = self._handle, monthly = monthly,
                                         lease_end = lease_end, kind = kind, successor = successor )

    def _successor( self, kind, cleaned ) -> Vehicle:
        # The successor's identity and first-purchase date are supplied at materialization from the
        # disposition (handle derived from the lease, purchase date the lease end); its payment method is
        # fixed by the kind (not a picked field); the name carries the leased vehicle's for the run table.
        spec = { **self._purchase_spec( cleaned ), 'payment_method' : _SUCCESSOR_METHOD[ kind ] }
        return Vehicle( handle = '', name = self._leased_name(), purchase_date = None, **spec )

    def _leased_name( self ) -> str:
        leased = self._profile.leased_vehicles if self._profile is not None else list()
        vehicle = next( ( v for v in leased if v.handle == self._handle ), None )
        return vehicle.name if vehicle is not None else ''

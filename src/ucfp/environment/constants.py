import json


class AppConst:
    """
    Single source of truth for string constants shared between Python
    (templates) and JavaScript.

    Many element ids, CSS classes, and data-attribute names/values are emitted
    by template code and then referenced by JavaScript. Rather than duplicate
    hard-coded magic strings on each side (and risk drift), define each shared
    value here exactly ONCE:

        - Template access:   ``{{ AppConst.NAME }}``  (the class is injected by
                             the shared_constants context processor)
        - JavaScript access: ``AppConst.NAME``        (a JSON-serialized copy is
                             injected into ``window.AppConst`` by pages/base.html)

    Because the JavaScript copy is generated from this class, the two sides
    cannot drift.

    Conventions:
        - JavaScript is responsible for deriving CSS selector forms (e.g.
          prefixing a class name with ``.``) as needed.
        - Data-attribute entries hold the jQuery ``.data()`` key WITHOUT the
          ``data-`` prefix and are named with a ``_DATA_ATTR`` suffix; for raw
          HTML/CSS, prepend ``data-`` explicitly.

    Add shared constants below as features need them.
    """

    # --- Inputs section (static/js/inputs.js) -----------------------------
    # The income table's date/age convenience columns and its background
    # auto-save. The date is canonical; each age field is kept in lockstep
    # client-side. Autosave is keyed off a form marker class, not an id, so any
    # inputs form opting in gets silent background saving.

    AUTOSAVE_CLASS = 'js-autosave'  # marks a <form> whose edits auto-save
    DATE_FIELD_CLASS = 'js-date'    # a date input: enhanced with a date picker
    AGE_FIELD_CLASS  = 'js-age'     # the age input beside a date in a date/age pair

    # A date input's planning context, which tunes where its picker opens and
    # how far it ranges (dates here are routinely decades from today, so the
    # picker must not be anchored to the current month). Read by inputs.js.
    DATE_CONTEXT_DATA_ATTR = 'date-context'
    DATE_CONTEXT_FUTURE    = 'future'     # opens today-forward (the common case)
    DATE_CONTEXT_PAST      = 'past'       # no future dates; fast year navigation
    DATE_CONTEXT_BIRTHDATE = 'birthdate'  # a past date bounded at today

    # Data-attribute tokens (jQuery .data() keys; prepend ``data-`` for raw
    # HTML) wiring one date/age field to its partner and to its subject's
    # (fixed) birthdate.
    BIRTHDATE_DATA_ATTR     = 'birthdate'
    AGE_FIELD_DATA_ATTR     = 'age-field'
    DATE_FIELD_DATA_ATTR    = 'date-field'

    # An optional block revealed on demand (e.g. a plan's second person): the
    # body is collapsed until "add" is clicked and cleared when "remove" is,
    # so the server infers the block's presence purely from whether its fields
    # are filled -- no separate "include this?" checkbox. Driven by inputs.js.
    OPTIONAL_CLASS        = 'js-optional'         # the wrapper
    OPTIONAL_ADD_CLASS    = 'js-optional-add'     # reveals the body
    OPTIONAL_BODY_CLASS   = 'js-optional-body'    # the optional fields
    OPTIONAL_REMOVE_CLASS = 'js-optional-remove'  # clears + collapses the body

    # A switch: a control (radio group / select) whose value reveals one of several sibling case
    # blocks and hides the rest (e.g. own vs rent showing different fields). All blocks render
    # visible without JS -- the server reads only the fields the chosen case makes relevant. Driven
    # by inputs.js.
    SWITCH_CLASS         = 'js-switch'          # the wrapper (control + cases)
    SWITCH_CONTROL_CLASS = 'js-switch-control'  # the control whose value selects the case
    SWITCH_CASE_DATA_ATTR = 'switch-case'       # a case block's value(s), space-separated

    # The credit-card paydown calculator (one per card, in the debt-plan step). The wrapper is also a
    # js-switch (mode radios reveal the monthly/date inputs); these mark the pieces the calculator
    # reads to show a live, advisory "how long / how much" readout. The authoritative resolution is
    # server-side (materialization), so the calculator is display-only. The APR both the calculator
    # and materialization assume is shared here so the two cannot drift.
    CREDIT_CARD_CLASS             = 'js-credit-card'          # the per-card widget wrapper
    CREDIT_CARD_MONTHLY_CLASS     = 'js-credit-card-monthly'  # the monthly-payment input (MONTHLY)
    CREDIT_CARD_DATE_CLASS        = 'js-credit-card-date'     # the target/payoff date input
    CREDIT_CARD_READOUT_CLASS     = 'js-credit-card-readout'  # where the live figure is written
    CREDIT_CARD_BALANCE_DATA_ATTR = 'card-balance'            # the card's balance, on the wrapper
    # The assumed card APR (from inputs.builtin_assumptions) rides here as a percent so the client
    # calculator reads the same value the engine uses; the server renders it onto the wrapper.
    CREDIT_CARD_APR_DATA_ATTR     = 'card-apr'                # the assumed APR (percent), on the wrapper

    # The loan payment calculator (one per amortizing debt, in the debt-plan step). The wrapper carries
    # the current balance (a Profile fact); these mark the rate/term/extra inputs the calculator reads
    # to show a live, advisory monthly-payment estimate. Display-only -- materialization is authoritative.
    LOAN_CLASS              = 'js-loan'          # the per-loan widget wrapper
    LOAN_RATE_CLASS         = 'js-loan-rate'     # the interest-rate input (percent)
    LOAN_TERM_CLASS         = 'js-loan-term'     # the remaining-term input (months)
    LOAN_EXTRA_CLASS        = 'js-loan-extra'    # the extra-principal-per-month input
    LOAN_READOUT_CLASS      = 'js-loan-readout'  # where the live estimate is written
    LOAN_BALANCE_DATA_ATTR  = 'loan-balance'     # the loan's current balance, on the wrapper

    # The recurring-expenses table's per-column delete: the x stamps its span index into the form's
    # hidden `delete_span` field, then triggers the autosave, so the server drops that span.
    RECURRING_DELETE_CLASS  = 'js-recurring-delete'  # the per-column x control (carries data-span)

    # The property-expenses matrix's live default->placeholder mirror. A per-property cell shows the
    # row's shared Default as its placeholder (what a blank cell falls back to); editing the Default
    # updates those placeholders client-side, since the pane saves silently and never re-renders them.
    PROPERTY_DEFAULT_CLASS  = 'js-property-default'   # a row's Default amount input
    PROPERTY_OVERRIDE_CLASS = 'js-property-override'  # a per-property override input in the same row

    # A durable expense's count-entry calculator (Appliance, Lawn Tools, Computer Purchase). A toggle
    # reveals a panel of count/cost/cadence inputs; as they change, the client fills the amount
    # target(s) with count x cost and writes a live "per year" readout. The amount stays authoritative
    # (server-computed on save), so the calculator is a convenience, not a separate source of truth.
    CALC_CLASS         = 'js-calc'          # the wrapper (cell/row) holding a calculator + its target(s)
    CALC_TOGGLE_CLASS  = 'js-calc-toggle'   # the button that reveals/hides the panel
    CALC_PANEL_CLASS   = 'js-calc-panel'    # the collapsible panel of count/cost/cadence inputs
    CALC_TARGET_CLASS  = 'js-calc-target'   # an amount input the computed count x cost fills
    CALC_READOUT_CLASS = 'js-calc-readout'  # where the advisory "per year" figure is written

    @classmethod
    def to_json_dict_str( cls ):
        """
        Serialize the UPPER-cased str/int constants to a JSON string for the
        ``window.AppConst`` injection in pages/base.html.
        """
        constants = {
            key: value
            for key, value in vars( cls ).items()
            if key.isupper() and isinstance( value, ( str, int ) )
        }
        return json.dumps( constants, indent = 4 )

// Client-side behaviors for the inputs section. Two concerns live here:
//
//   AgeDateSync - the convenience age input beside a planning date (the Retirement timing pane). The
//     date is canonical; the age is kept in lockstep client-side so the server only ever reads dates.
//     Each date/age pair carries its subject's fixed birthdate as a data-attribute, so the sync is a
//     per-field attribute read.
//
//   AutoSave - silent background saving for any inputs form. On every edit the form is serialized
//     and posted via antinode with the loader suppressed; an empty reply means no DOM swap, so
//     typing flow is undisturbed. The server re-renders the pane only on a structural change (a line
//     added/removed) or a validation error.
//
//   DatePicker - enhances date inputs with a picker tuned to the field's planning context, since
//     these dates routinely sit decades from today. Unlike the two behaviors above it attaches to
//     concrete elements, so it is (re)applied on each antinode render rather than delegated.
//
//   OptionalSection - a block of fields collapsed behind an "add" trigger until wanted and cleared
//     by its "remove" trigger, so the server infers the block's presence from its fields alone. Its
//     open/collapsed state, like the pickers, is (re)applied on each antinode render.
//
//   SwitchGroup - a control (radio/select) whose value reveals one of several sibling case blocks
//     and hides the rest (e.g. own vs rent). Presentation only; (re)applied on each render.
//
// The delegated behaviors are wired on `body`, so they survive an antinode pane swap and bind
// exactly once. All the ids/classes/data-attributes shared with the templates come from
// window.AppConst (see ucfp/environment/constants.py) rather than hard-coded strings, so the two
// sides cannot drift.

window.App = window.App || {};
window.App.Inputs = (function () {
    'use strict';

    const C = window.AppConst;

    // The templates emit bare class/attribute tokens; JS derives the selector and attribute forms.
    const classSelector = name => '.' + name;
    const dataAttr      = name => 'data-' + name;

    // ----- AgeDateSync: keep an age input in step with its canonical date -----

    // A date/age field's birthdate is baked into the field as a data-attribute (the owning subject is
    // fixed), so resolving it is a plain attribute read.
    function birthdateFor( $field ) {
        return $field.attr( dataAttr( C.BIRTHDATE_DATA_ATTR ) ) || null;
    }

    // The birthday in (birth.year + age); 29 Feb in a non-leap target year falls back to the 28th,
    // matching the server's _at_age.
    function atAge( birthIso, age ) {
        const parts = birthIso.split( '-' );
        const year = parseInt( parts[0], 10 ) + age;
        const month = parts[1];
        let day = parts[2];
        if ( month === '02' && day === '29' ) { day = '28'; }
        return [ year, month, day ].join( '-' );
    }

    // Whole-year age a date falls on -- the inverse of atAge, matching the server's _derived_age.
    function ageOf( dateIso, birthIso ) {
        return parseInt( dateIso.split( '-' )[0], 10 ) - parseInt( birthIso.split( '-' )[0], 10 );
    }

    function fillDateFromAge( $age ) {
        const birth = birthdateFor( $age );
        const age = parseInt( $age.val(), 10 );
        if ( birth && ! isNaN( age ) ) {
            const $date = $( '#' + $age.attr( dataAttr( C.DATE_FIELD_DATA_ATTR ) ) );
            $date.val( atAge( birth, age ) );
            syncPickerToValue( $date );   // the picker keeps its own date model; teach it the new value
        }
    }

    function refreshAgeFromDate( $date ) {
        const birth = birthdateFor( $date );
        const iso = $date.val();
        const $age = $( '#' + $date.attr( dataAttr( C.AGE_FIELD_DATA_ATTR ) ) );
        if ( birth && /^\d{4}-\d{2}-\d{2}$/.test( iso ) ) { $age.val( ageOf( iso, birth ) ); }
        else if ( ! iso ) { $age.val( '' ); }
    }

    // Dispatch a changed field to its side of the pair. A no-op for fields that are neither, so the
    // change handler can call it unconditionally before serializing.
    function syncField( $field ) {
        if ( $field.hasClass( C.AGE_FIELD_CLASS ) ) { fillDateFromAge( $field ); }
        else if ( $field.hasClass( C.DATE_FIELD_CLASS ) ) { refreshAgeFromDate( $field ); }
    }

    // ----- Read-only mode -----

    // Whether the member may edit the current organization. The server sets `data-can-edit` on <body>
    // (see the can_edit_organization context processor); when false the interface is presented read-only.
    function canEditOrganization() {
        return $( document.body ).attr( 'data-can-edit' ) !== 'false';
    }

    // Present the interface read-only: disable the self-saving panes' value controls so they show data
    // but take no input, and make the edit-only affordances (add/remove/reorder/save) inert -- they stay
    // visible for context (a true preview), but do nothing. Scoped so navigation (navbar, switcher,
    // sign-out) stays live. Runs on load and after each async render, like the enhancers, so swapped-in
    // content is neutralized too. A no-op when the member may edit.
    function neutralizeReadOnly( $scope ) {
        if ( canEditOrganization() ) { return; }
        const $root = $scope || $( document.body );
        const autosaveForm = 'form' + classSelector( C.AUTOSAVE_CLASS );
        $root.find( autosaveForm ).addBack( autosaveForm )
            .find( 'input, select, textarea' ).not( '[disabled]' ).prop( 'disabled', true );
        // Edit-only affordances (and edit-only form regions, e.g. Settings) are muted and pointer-inert
        // via CSS; disable every control they hold and drop links from the tab order for keyboard/AT.
        const $affordances = $root.find( '.edit-only' ).addBack( '.edit-only' );
        $affordances.attr( 'aria-disabled', 'true' );
        $affordances.find( ':input' ).addBack( ':input' ).prop( 'disabled', true );
        $affordances.filter( 'a' ).attr( 'tabindex', '-1' );
    }

    // ----- AutoSave: silent background persistence -----

    function saveForm( $form ) {
        if ( !canEditOrganization() ) { return; }   // a read-only member never persists
        AN.post( $form.attr( 'action' ), $form.serialize(), { suppressLoader: true } );
    }

    // Whether the changed field sits in a both-or-neither group (PAIR_CLASS) that is still half-filled
    // -- a person mid-entry (a name typed, its birthdate not yet). While so, the autosave holds off, so
    // the incomplete-pair error (and the pane re-render that would steal focus from the field being
    // filled) never fires until the pair is whole. Fields in no such group -- and a group wholly filled
    // or wholly empty -- return false and save normally.
    function pairMidEntry( $field ) {
        const $pair = $field.closest( classSelector( C.PAIR_CLASS ) );
        if ( ! $pair.length ) { return false; }
        const values = $pair.find( ':input' ).map( function () { return ( $( this ).val() || '' ).trim(); } ).get();
        const filled = values.filter( Boolean ).length;
        return filled > 0 && filled < values.length;
    }

    // ----- Money inputs: thousands grouping -----
    //
    // Money fields are plain text inputs (not number) so their value can carry thousands separators.
    // Grouping runs as the user types (keeping the caret at the same digit) and once on the server-
    // rendered initial values (enhanceMoneyInputs, on load and after each antinode render). The value
    // stays a bare number to the server -- the MoneyField strips the separators on the way in -- and
    // any client-side reader of a money value parses it through `parseAmount`, which tolerates them.

    function groupedThousands( value ) {
        const cleaned = String( value ).replace( /[^\d.]/g, '' );        // keep only digits and the point
        if ( cleaned === '' ) { return ''; }
        const dot   = cleaned.indexOf( '.' );
        const whole = dot === -1 ? cleaned : cleaned.slice( 0, dot );
        const frac  = dot === -1 ? '' : '.' + cleaned.slice( dot + 1 ).replace( /\./g, '' );
        return whole.replace( /\B(?=(\d{3})+(?!\d))/g, ',' ) + frac;
    }

    // parseFloat, tolerant of the thousands separators money inputs carry (a no-op on comma-less values).
    function parseAmount( value ) {
        return parseFloat( String( value == null ? '' : value ).replace( /,/g, '' ) );
    }

    function digitsBefore( value, caret ) {
        return ( value.slice( 0, caret ).match( /\d/g ) || [] ).length;
    }

    function caretPastDigits( value, digits ) {
        if ( digits <= 0 ) { return 0; }
        let seen = 0;
        for ( let i = 0; i < value.length; i++ ) {
            if ( /\d/.test( value[ i ] ) && ++seen === digits ) { return i + 1; }
        }
        return value.length;
    }

    // Regroup a money input in place, keeping the caret at the same digit so typing is undisturbed.
    function groupMoneyInput( input ) {
        const wanted    = digitsBefore( input.value, input.selectionStart );
        const formatted = groupedThousands( input.value );
        if ( formatted === input.value ) { return; }
        input.value = formatted;
        const caret = caretPastDigits( formatted, wanted );
        input.setSelectionRange( caret, caret );
    }

    function enhanceMoneyInputs( $scope ) {
        const sel = classSelector( C.MONEY_INPUT_CLASS );
        ( $scope || $( document.body ) ).find( sel ).addBack( sel ).each( function () {
            this.value = groupedThousands( this.value );
        } );
    }

    // ----- DatePicker: enhance date inputs, tuned to their planning context -----
    //
    // Dates here routinely sit decades from today (birthdates back, planning dates ahead), so a
    // picker anchored to the current month is the wrong tool. The value stays canonical ISO so the
    // server reads yyyy-mm-dd whether or not the picker loads (progressive enhancement).

    // Options shared by every context.
    const DATEPICKER_BASE = {
        format           : 'yyyy-mm-dd',
        autoclose        : true,
        todayHighlight   : true,
        assumeNearbyYear : true,          // a typed 2-digit year snaps to the nearest century
        orientation      : 'bottom auto',
    };

    // Dates here routinely sit years out (or decades back), so every context opens on the
    // decade-of-years view (startView 2): reaching a far year is a couple of clicks (and a decade
    // arrow to jump ten years) rather than months of paging. Past-facing contexts additionally cap at
    // today.
    function datepickerOptions( context ) {
        if ( context === C.DATE_CONTEXT_BIRTHDATE || context === C.DATE_CONTEXT_PAST ) {
            return Object.assign( {}, DATEPICKER_BASE, { endDate : '+0d', startView : 2 } );
        }
        return Object.assign( {}, DATEPICKER_BASE, { startView : 2 } );
    }

    // A private flag (data-dp-enhanced) marks inputs already wired, so re-scanning after an antinode
    // swap -- or over an overlapping scope -- never double-initializes a picker.
    const ENHANCED_FLAG = 'dpEnhanced';

    function eachDateField( $scope, fn ) {
        const sel = classSelector( C.DATE_FIELD_CLASS );
        $scope.find( sel ).addBack( sel ).each( function () { fn( $( this ) ); } );
    }

    // Enhance every not-yet-enhanced date input under `$scope`. A no-op if the picker asset failed
    // to load, leaving a usable plain ISO text box.
    function enhanceDates( $scope ) {
        if ( ! $.fn.datepicker ) { return; }
        eachDateField( $scope || $( document.body ), function ( $field ) {
            if ( $field.data( ENHANCED_FLAG ) ) { return; }
            $field.datepicker( datepickerOptions( $field.attr( dataAttr( C.DATE_CONTEXT_DATA_ATTR ) ) ) );
            $field.data( ENHANCED_FLAG, true );
        } );
    }

    // Push a programmatically-set value into an enhanced input's picker. bootstrap-datepicker keeps its
    // own date model, so a bare `.val()` (as the age->date sync does) leaves the popup on its stale
    // internal date -- it would open on today and commit today on Enter or a tab-in. `update` re-reads the
    // input, so the popup instead opens on (and commits) the shown date. A no-op when the picker asset
    // never loaded or the field is not yet enhanced -- the plain text box already shows the right value.
    function syncPickerToValue( $date ) {
        if ( $.fn.datepicker && $date.data( ENHANCED_FLAG ) ) {
            $date.datepicker( 'update' );
        }
    }

    // Tear down pickers in a subtree about to be removed, so no detached popup is orphaned.
    function destroyDates( $scope ) {
        if ( ! $.fn.datepicker || ! $scope ) { return; }
        eachDateField( $scope, function ( $field ) {
            if ( $field.data( ENHANCED_FLAG ) ) {
                $field.datepicker( 'destroy' );
                $field.removeData( ENHANCED_FLAG );
            }
        } );
    }

    // ----- OptionalSection: a revealable block, cleared when dismissed -----
    //
    // An optional group of fields (e.g. a plan's second person) collapsed behind an "add" trigger
    // until wanted, and cleared by its "remove" trigger. The server reads presence straight from the
    // fields -- a filled body means present -- so removing MUST clear, or a hidden-but-filled field
    // would silently resurrect the block. Without JS the body renders visible and usable; the two
    // triggers render `hidden`, so no dead controls show.

    function optionalParts( $section ) {
        return {
            add    : $section.children( classSelector( C.OPTIONAL_ADD_CLASS ) ),
            body   : $section.children( classSelector( C.OPTIONAL_BODY_CLASS ) ),
            remove : $section.find( classSelector( C.OPTIONAL_REMOVE_CLASS ) ),
            toggle : $section.find( classSelector( C.OPTIONAL_TOGGLE_CLASS ) ),
        };
    }

    function setOptionalOpen( $section, open ) {
        const parts = optionalParts( $section );
        parts.body.prop( 'hidden', ! open );
        parts.add.prop( 'hidden', open );      // button style: the add button hides once open
        parts.remove.prop( 'hidden', ! open ); // button style: the remove button shows only while open
        parts.toggle.prop( 'checked', open );  // checkbox style: the checkbox reflects the open state
    }

    // Clear an optional body (so the server reads it as absent) and collapse it, persisting the removal --
    // clearing fires no `change`, so an autosave form must be told to save. Shared by the remove button and
    // the toggle checkbox when it is unchecked.
    function clearAndCollapseOptional( $section ) {
        optionalParts( $section ).body.find( ':input' )
            .val( '' ).filter( ':checkbox, :radio' ).prop( 'checked', false );
        setOptionalOpen( $section, false );
        const $form = $section.closest( 'form' + classSelector( C.AUTOSAVE_CLASS ) );
        if ( $form.length ) { saveForm( $form ); }
    }

    // Whether any field in the body carries a value -- the same "is it present?" test the server
    // applies, so the opened/collapsed state on load matches what a submit would infer.
    function bodyIsFilled( $body ) {
        let filled = false;
        $body.find( ':input' ).each( function () {
            const $input = $( this );
            if ( $input.is( ':checkbox, :radio' ) ) {
                if ( $input.prop( 'checked' ) ) { filled = true; }
            } else if ( $.trim( $input.val() || '' ) !== '' ) {
                filled = true;
            }
        } );
        return filled;
    }

    function enhanceOptionalSections( $scope ) {
        const $root = $scope || $( document.body );
        $root.find( classSelector( C.OPTIONAL_CLASS ) ).each( function () {
            const parts = optionalParts( $( this ) );
            // Where a toggle checkbox is present, its checked state holds the open-state *within the
            // current DOM* -- the user's explicit choice, which may be an intentionally-opened-but-still-
            // empty block, honoured each time this runs (after every async render). The checkbox carries no
            // name and is always server-rendered unchecked, so across a server re-render the open-state is
            // reconstructed from bodyIsFilled alone; or-ing it in also auto-opens an existing block on first
            // load. The button style has no toggle control, so it falls back to bodyIsFilled alone.
            setOptionalOpen( $( this ), parts.toggle.prop( 'checked' ) || bodyIsFilled( parts.body ) );
        } );
    }

    // ----- SwitchGroup: reveal the case block matching a control's value -----
    //
    // A control (radio group or select) inside a `js-switch` wrapper picks which sibling case block
    // shows; the rest hide. Every case renders visible without JS -- the server reads only the fields
    // the chosen case makes relevant -- so this is pure presentation, (re)applied on load and after
    // each render, plus live on the control's change.

    // The controls / case blocks belonging to *this* switch, not a nested one -- so switches can nest
    // (a disposition's kind switch containing a payment switch): each answers only to its own control.
    // For a lone switch every match's nearest `.js-switch` is itself, so this is a no-op there.
    function ownedBy( $switch, $elements ) {
        return $elements.filter( function () {
            return $( this ).closest( classSelector( C.SWITCH_CLASS ) )[ 0 ] === $switch[ 0 ];
        } );
    }

    function switchValue( $switch ) {
        const $control = ownedBy( $switch, $switch.find( classSelector( C.SWITCH_CONTROL_CLASS ) ) );
        const $checked = $control.filter( ':radio:checked' );
        return $checked.length ? $checked.val() : $control.not( ':radio' ).val();
    }

    function applySwitch( $switch ) {
        const value = switchValue( $switch );
        ownedBy( $switch, $switch.find( '[' + dataAttr( C.SWITCH_CASE_DATA_ATTR ) + ']' ) ).each( function () {
            const $case = $( this );
            const cases = ( $case.attr( dataAttr( C.SWITCH_CASE_DATA_ATTR ) ) || '' ).split( /\s+/ );
            $case.prop( 'hidden', cases.indexOf( value ) === -1 );
        } );
    }

    function enhanceSwitches( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.SWITCH_CLASS ) )
            .each( function () { applySwitch( $( this ) ); } );
    }

    // ----- ResidenceOption: reveal a residence-only sale option for a residence sale -----
    //
    // The "Sell a property" add form offers a "Rent after selling your home" option that applies only to
    // selling the primary residence (a second-home/rental sale ignores it). The form carries the
    // residence handle(s) and marks that option's container residence-gated; this shows the container
    // only while the property picker's value is one of those handles, and hides it otherwise. Presentation
    // only -- materialization already ignores the option for a non-residence sale -- so no submit-value
    // handling is needed. (Re)applied on load and after each render, plus live on the picker's change.
    // A residence handle is a property handle, so the property picker is the only select whose value can
    // match; scanning the form's selects therefore needs no marker to single it out.

    function residenceHandles( $form ) {
        return ( $form.attr( dataAttr( C.RESIDENCE_HANDLES_DATA_ATTR ) ) || '' ).split( /\s+/ ).filter( Boolean );
    }

    function residenceIsChosen( $form, handles ) {
        let chosen = false;
        $form.find( 'select' ).each( function () {
            if ( handles.indexOf( $( this ).val() ) !== -1 ) { chosen = true; }
        } );
        return chosen;
    }

    function applyResidenceOptions( $form ) {
        const shown = residenceIsChosen( $form, residenceHandles( $form ) );
        $form.find( '[' + dataAttr( C.REQUIRES_RESIDENCE_DATA_ATTR ) + ']' ).prop( 'hidden', ! shown );
    }

    function enhanceResidenceOptions( $scope ) {
        const sel = '[' + dataAttr( C.RESIDENCE_HANDLES_DATA_ATTR ) + ']';
        ( $scope || $( document.body ) ).find( sel ).addBack( sel )
            .each( function () { applyResidenceOptions( $( this ) ); } );
    }

    // ----- StateTaxAutofill: fill the state income-tax rate from the chosen state -----
    // Picking a state copies that option's representative rate (a data attribute on the option) into
    // the rate input, which the user may then override. Bound directly on the select so it fires in
    // the target phase, before the form's delegated autosave serializes -- so the filled rate is saved
    // in the same request. Re-applied after each render; namespaced to stay idempotent.

    function enhanceStateAutofill( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.STATE_SELECT_CLASS ) )
            .off( 'change.stateAutofill' )
            .on( 'change.stateAutofill', function () {
                const $select = $( this );
                const rate    = $select.find( 'option:selected' )
                    .attr( dataAttr( C.STATE_RATE_DATA_ATTR ) );
                $select.closest( 'form' ).find( classSelector( C.STATE_RATE_CLASS ) )
                    .val( rate || '' );
                showStateExemptions( $select );
            } )
            .each( function () { showStateExemptions( $( this ) ); } );   // populate on load
    }

    // Display-only: write the chosen state's retirement-income exemption words (carried per option) into
    // the read-only readout, or clear it for the "other" option and no-income-tax states.
    function showStateExemptions( $select ) {
        const $option    = $select.find( 'option:selected' );
        const ss         = $option.attr( dataAttr( C.STATE_SS_STATUS_DATA_ATTR ) ) || '';
        const retirement = $option.attr( dataAttr( C.STATE_RETIREMENT_STATUS_DATA_ATTR ) ) || '';
        const $readout   = $select.closest( 'form' ).find( classSelector( C.STATE_EXEMPTIONS_CLASS ) );
        if ( ss || retirement ) {
            $readout.empty()
                .append( $( '<div>' ).text( 'Social Security: ' + ss ) )
                .append( $( '<div>' ).text( 'Pensions & retirement: ' + retirement ) );
        } else {
            $readout.empty();
        }
    }

    // ----- CreditCardCalculator: a live, advisory paydown figure per card -----
    // Display-only. As a card's mode/inputs change, write a "how long / how much" figure into its
    // readout at the assumed APR the card widget carries (rendered from BUILTIN_ASSUMPTIONS, the same
    // value materialization resolves at). The authoritative resolution is server-side; this guides entry.

    function cardMonthlyRate( $card ) {
        return ( parseFloat( $card.attr( dataAttr( C.CREDIT_CARD_APR_DATA_ATTR ) ) ) || 0 ) / 100 / 12;
    }

    function cardBalance( $card ) {
        return parseFloat( $card.attr( dataAttr( C.CREDIT_CARD_BALANCE_DATA_ATTR ) ) ) || 0;
    }

    // The readout "kind" the form marked on the checked mode option -- the JS branches on this
    // presentation vocabulary, not the CreditCardPlanMode member names.
    function cardModeKind( $card ) {
        return $card.find( classSelector( C.SWITCH_CONTROL_CLASS ) ).filter( ':checked' )
            .attr( dataAttr( C.CARD_MODE_KIND_DATA_ATTR ) );
    }

    // Months of `payment` to clear `balance` at the card rate, or null when it never does (the
    // payment does not cover the interest) -- the client mirror of common.amortization.periods_to_repay.
    function monthsToClear( balance, payment, rate ) {
        if ( balance <= 0 ) { return 0; }
        if ( rate > 0 && payment <= balance * rate ) { return null; }
        const cap = C.MAX_PLAUSIBLE_LOAN_TERM_MONTHS;   // shared with the server's periods_to_repay bound
        let remaining = balance, months = 0;
        while ( remaining > 0 && months < cap ) {
            months += 1;
            const payoff = remaining + remaining * rate;
            if ( payment >= payoff ) { return months; }
            remaining = payoff - payment;
        }
        return months < cap ? months : null;
    }

    // The level payment that clears `balance` over `months` at the card rate (mirror of level_payment).
    function paymentForMonths( balance, months, rate ) {
        if ( months <= 0 ) { return null; }
        if ( rate === 0 ) { return balance / months; }
        const discount = Math.pow( 1 + rate, -months );
        return balance * rate / ( 1 - discount );
    }

    // The balance left after `months` payments of `payment` at the card rate (mirror of balance_after).
    function balanceAfter( balance, payment, months, rate ) {
        let remaining = balance;
        for ( let i = 0; i < months && remaining > 0; i += 1 ) {
            remaining = remaining + remaining * rate - payment;
        }
        return Math.max( remaining, 0 );
    }

    function monthsUntil( iso ) {
        const parts = ( iso || '' ).split( '-' );
        if ( parts.length !== 3 ) { return null; }
        const now = new Date();
        return ( parseInt( parts[ 0 ], 10 ) - now.getFullYear() ) * 12
             + ( parseInt( parts[ 1 ], 10 ) - 1 - now.getMonth() );
    }

    function money( amount ) { return '$' + Math.round( amount ).toLocaleString(); }

    function describeMonths( months ) {
        if ( months < 12 ) { return months + ( months === 1 ? ' month' : ' months' ); }
        const years = Math.round( months / 12 );
        return 'about ' + years + ( years === 1 ? ' year' : ' years' );
    }

    function cardReadout( $card ) {
        const balance = cardBalance( $card );
        const rate = cardMonthlyRate( $card );
        const kind = cardModeKind( $card );
        const monthly = function () {
            return parseAmount( $card.find( classSelector( C.CREDIT_CARD_MONTHLY_CLASS ) ).val() );
        };
        const targetMonths = function () {
            return monthsUntil( $card.find( classSelector( C.CREDIT_CARD_DATE_CLASS ) ).val() );
        };
        // Carrying it (the default) and a lump payoff both cost only the interest each month.
        if ( kind === C.CARD_READOUT_INTEREST_ONLY || !kind ) {
            return 'Carrying it costs about ' + money( balance * rate ) + '/month in interest.';
        }
        if ( kind === C.CARD_READOUT_CLEARS_BY_PAYMENT ) {
            const payment = monthly();
            if ( !( payment > 0 ) ) { return ''; }
            const months = monthsToClear( balance, payment, rate );
            return months === null
                ? 'That won\'t cover the interest, so the balance never clears.'
                : 'Clears in ' + describeMonths( months ) + '.';
        }
        if ( kind === C.CARD_READOUT_PAYMENT_FOR_DATE ) {
            const months = targetMonths();
            if ( !months || months <= 0 ) { return ''; }
            return 'That needs about ' + money( paymentForMonths( balance, months, rate ) ) + '/month.';
        }
        if ( kind === C.CARD_READOUT_BALANCE_AT_DATE ) {
            const payment = monthly(), months = targetMonths();
            if ( !( payment > 0 ) || !months || months <= 0 ) { return ''; }
            const cleared = monthsToClear( balance, payment, rate );
            if ( cleared !== null && cleared <= months ) { return 'Paid off before that date at this rate.'; }
            return 'Leaves about ' + money( balanceAfter( balance, payment, months, rate ) ) + ' to pay off then.';
        }
        return '';
    }

    function updateCard( $card ) {
        $card.find( classSelector( C.CREDIT_CARD_READOUT_CLASS ) ).first().text( cardReadout( $card ) );
    }

    function enhanceCreditCards( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.CREDIT_CARD_CLASS ) )
            .each( function () { updateCard( $( this ) ); } );
    }

    // ----- LoanCalculator: one loan widget over balance / rate / term / payment -----
    // The shared client mirror for every loan-entry surface. The balance is either a fixed fact on the
    // block (the debt-plan and current-loan cards) or an editable input (the Profile loan entries); a
    // surface exposes whichever of rate / term / payment it edits, and this adapts to what is present:
    //   - where a payment input exists, the four quantities are kept consistent by the preferred trio
    //     (balance + rate + term authoritative, payment re-derived) -- editing the balance, rate, or term
    //     re-derives the payment; editing the payment instead back-solves the rate (the number people
    //     don't know), blanking it and showing the hint when the payment/term don't fit the balance;
    //   - where a readout element exists, it writes the level payment (and any extra-principal payoff) the
    //     terms imply as an advisory line.
    // Entry aid only -- materialization is authoritative. Mirrors common/loan_solver.py and
    // common/amortization.py; the plausibility ceiling is read off AppConst (its one source).

    function loanField( $loan, cls ) {
        return parseAmount( $loan.find( classSelector( cls ) ).val() );
    }

    // The balance from the editable input where the surface has one (Profile), else the fixed fact on the
    // wrapper (the debt-plan / current-loan cards).
    function loanBalance( $loan ) {
        const $input = $loan.find( classSelector( C.LOAN_BALANCE_CLASS ) );
        if ( $input.length ) { return parseAmount( $input.val() ) || 0; }
        return parseFloat( $loan.attr( dataAttr( C.LOAN_BALANCE_DATA_ATTR ) ) ) || 0;
    }

    function loanMonths( $loan ) {
        return parseInt( $loan.find( classSelector( C.LOAN_TERM_CLASS ) ).val(), 10 ) || 0;
    }

    // The interest rate as a percent, or NaN when the field is blank -- a blank rate is "not entered" while
    // an entered 0 is a real 0% loan, so callers test `>= 0` (NaN fails that, 0 passes).
    function loanRatePercent( $loan ) {
        return parseFloat( $loan.find( classSelector( C.LOAN_RATE_CLASS ) ).val() );
    }

    // A whole-month term as "29 yr 11 mo" (either part dropped when zero, but never both).
    function describeTerm( months ) {
        const whole = Math.round( months );
        const years = Math.floor( whole / 12 ), rest = whole % 12;
        const parts = [];
        if ( years ) { parts.push( years + ' yr' ); }
        if ( rest || !years ) { parts.push( rest + ' mo' ); }
        return parts.join( ' ' );
    }

    // The monthly rate at which `payment` retires `balance` over `months` (mirror of rate_for_payment):
    // bisected, since the payment rises monotonically with the rate; 0 when the payment does not exceed
    // the zero-interest payment.
    function rateForPayment( balance, payment, months ) {
        if ( months <= 0 || payment <= balance / months ) { return 0; }
        let low = 0, high = 1;                            // 0 .. 100% per period brackets every real loan
        for ( let i = 0; i < 60; i++ ) {
            const mid = ( low + high ) / 2;
            if ( paymentForMonths( balance, months, mid ) < payment ) { low = mid; } else { high = mid; }
        }
        return ( low + high ) / 2;
    }

    const MAX_PLAUSIBLE_APR = C.MAX_PLAUSIBLE_LOAN_APR_PERCENT;   // percent; one source, in AppConst

    // Editing the balance, rate, or term re-derives the monthly payment: the level payment amortizing the
    // balance over the months left. The authoritative trio is explicit, so clear the "doesn't fit" hint.
    function fillLoanPayment( $loan ) {
        const balance = loanBalance( $loan ), months = loanMonths( $loan );
        const ratePercent = loanRatePercent( $loan );
        if ( !( balance > 0 ) || !( months > 0 ) || !( ratePercent >= 0 ) ) { return; }
        setMoneyField( $loan.find( classSelector( C.LOAN_PAYMENT_CLASS ) ),
                       paymentForMonths( balance, months, ( ratePercent / 100 ) / 12 ) );
        $loan.find( classSelector( C.LOAN_HINT_CLASS ) ).addClass( 'd-none' );
    }

    // Editing the payment back-solves the rate -- the annual rate that payment implies over the balance and
    // term. The payment must retire the balance in the term and imply a plausible rate; otherwise it does
    // not form a real loan, so leave the rate blank and show the hint rather than guess an implausible rate.
    function fillLoanRate( $loan ) {
        const balance = loanBalance( $loan ), months = loanMonths( $loan );
        const payment = parseAmount( $loan.find( classSelector( C.LOAN_PAYMENT_CLASS ) ).val() );
        if ( !( balance > 0 ) || !( months > 0 ) || !( payment > 0 ) ) { return; }
        const annualPercent = rateForPayment( balance, payment, months ) * 12 * 100;
        const fits = ( payment * months >= balance ) && ( annualPercent <= MAX_PLAUSIBLE_APR );
        $loan.find( classSelector( C.LOAN_RATE_CLASS ) ).val( fits ? annualPercent.toFixed( 2 ) : '' );
        $loan.find( classSelector( C.LOAN_HINT_CLASS ) ).toggleClass( 'd-none', fits );
    }

    // Back-solve the remaining term -- the months this payment takes to clear the balance at the rate
    // ("how long until it's paid off?"). A payment that cannot retire the balance (or would take an absurd
    // span) forms no real loan, so leave the term blank and show the hint rather than an implausible term.
    function fillLoanTerm( $loan ) {
        const balance = loanBalance( $loan ), payment = loanField( $loan, C.LOAN_PAYMENT_CLASS );
        const ratePercent = loanRatePercent( $loan );
        if ( !( balance > 0 ) || !( ratePercent >= 0 ) || !( payment > 0 ) ) { return; }
        const months = monthsToClear( balance, payment, ( ratePercent / 100 ) / 12 );
        $loan.find( classSelector( C.LOAN_TERM_CLASS ) ).val( months === null ? '' : months );
        $loan.find( classSelector( C.LOAN_HINT_CLASS ) ).toggleClass( 'd-none', months !== null );
    }

    // Re-derive the balance where the surface edits it (the Profile entries) -- the principal these terms
    // imply (the present value of the payments). Always computable from rate + term + payment, so clear the
    // hint.
    function fillLoanBalance( $loan ) {
        const months = loanMonths( $loan ), payment = loanField( $loan, C.LOAN_PAYMENT_CLASS );
        const ratePercent = loanRatePercent( $loan );
        if ( !( months > 0 ) || !( ratePercent >= 0 ) || !( payment > 0 ) ) { return; }
        setMoneyField( $loan.find( classSelector( C.LOAN_BALANCE_CLASS ) ),
                       presentValue( payment, months, ( ratePercent / 100 ) / 12 ) );
        $loan.find( classSelector( C.LOAN_HINT_CLASS ) ).addClass( 'd-none' );
    }

    // The advisory readout (where a surface has one): the level payment the terms imply, plus any
    // extra-principal payoff. Empty until balance, rate, and term are all set.
    function loanReadout( $loan ) {
        const balance = loanBalance( $loan );
        const ratePercent = loanRatePercent( $loan );
        const months = loanMonths( $loan );
        if ( !( balance > 0 ) || !( ratePercent >= 0 ) || !( months > 0 ) ) { return ''; }
        const rate = ( ratePercent / 100 ) / 12;
        const payment = paymentForMonths( balance, months, rate );
        let text = 'About ' + money( payment ) + '/month over ' + describeTerm( months ) + '.';
        const extra = loanField( $loan, C.LOAN_EXTRA_CLASS );
        if ( extra > 0 ) {
            const payoff = monthsToClear( balance, payment + extra, rate );
            if ( payoff !== null ) {
                text += ' With ' + money( extra ) + ' extra/month, pays off in about '
                    + describeTerm( payoff ) + '.';
            }
        }
        return text;
    }

    function updateLoanReadout( $loan ) {
        const $readout = $loan.find( classSelector( C.LOAN_READOUT_CLASS ) ).first();
        if ( $readout.length ) { $readout.text( loanReadout( $loan ) ); }
    }

    // The four loan quantities in knownness order, least-known first: balance and remaining term drift month
    // to month (the vaguest), the rate is a remembered ballpark, the payment is seen every month (the surest).
    // The sink policy re-derives the least-known field the surface lets it write. `has` reports whether the
    // field currently holds a usable value; `writeable` whether this surface renders it as an editable input
    // (balance is a fixed fact on the current-loan cards, an input only on the Profile entries).
    function loanHas( $loan, cls ) {
        if ( cls === C.LOAN_BALANCE_CLASS ) { return loanBalance( $loan ) > 0; }
        if ( cls === C.LOAN_TERM_CLASS )    { return loanMonths( $loan ) > 0; }
        if ( cls === C.LOAN_RATE_CLASS )    { return loanRatePercent( $loan ) >= 0; }
        return loanField( $loan, cls ) > 0;                  // payment
    }

    function loanWriteable( $loan, cls ) {
        return $loan.find( classSelector( cls ) ).length > 0;
    }

    const LOAN_QUANTITIES = [
        { cls: C.LOAN_BALANCE_CLASS, fill: fillLoanBalance },
        { cls: C.LOAN_TERM_CLASS,    fill: fillLoanTerm },
        { cls: C.LOAN_RATE_CLASS,    fill: fillLoanRate },
        { cls: C.LOAN_PAYMENT_CLASS, fill: fillLoanPayment },
    ];

    // The pure sink decision, factored out so it can be unit-tested without the DOM: given the writeable
    // field classes (in knownness order, least-known first), which of them are currently blank, and the
    // class just edited, return the one field to (re-)derive -- the sole writeable blank that is not the
    // edited field (solve the missing quantity), else the least-known writeable field that is not the edited
    // field (re-derive it), else null (>=2 blanks is underdetermined, and nothing is derived while the edited
    // field is itself the only blank). Never returns the edited field, so an in-progress edit is never
    // overwritten.
    function selectLoanSink( writeableClasses, blankClasses, editedClass ) {
        if ( blankClasses.length === 1 && blankClasses[ 0 ] !== editedClass ) {
            return blankClasses[ 0 ];
        }
        if ( blankClasses.length === 0 ) {
            const others = writeableClasses.filter( function ( cls ) { return cls !== editedClass; } );
            return others.length ? others[ 0 ] : null;
        }
        return null;
    }

    // Which loan quantity the edited element is (its knownness-table class), or null -- so the sink
    // decision can exclude it.
    function editedLoanClass( $edited ) {
        const quantity = LOAN_QUANTITIES.filter( function ( q ) { return $edited.hasClass( q.cls ); } )[ 0 ];
        return quantity ? quantity.cls : null;
    }

    // Respond to an edit within a loan block (only where the block carries a payment input -- the
    // four-quantity solve): read which quantities this surface can write and which are blank, ask
    // selectLoanSink which single field to derive, fill it, then refresh any advisory readout.
    function solveLoan( $loan, $edited ) {
        if ( $loan.find( classSelector( C.LOAN_PAYMENT_CLASS ) ).length ) {
            const writeable = LOAN_QUANTITIES.filter( function ( q ) { return loanWriteable( $loan, q.cls ); } );
            const blanks    = writeable.filter( function ( q ) { return !loanHas( $loan, q.cls ); } );
            const sinkClass = selectLoanSink(
                writeable.map( function ( q ) { return q.cls; } ),
                blanks.map( function ( q ) { return q.cls; } ),
                editedLoanClass( $edited ) );
            if ( sinkClass ) {
                LOAN_QUANTITIES.filter( function ( q ) { return q.cls === sinkClass; } )[ 0 ].fill( $loan );
            }
        }
        updateLoanReadout( $loan );
    }

    function enhanceLoans( $scope ) {
        // Bound directly on each block's inputs (re-applied per render) so a filled value lands before the
        // form's change-driven autosave serializes; setting `.val()` fires no event, so the rate/payment
        // pair does not loop.
        ( $scope || $( document.body ) ).find( classSelector( C.LOAN_CLASS ) ).each( function () {
            const $loan = $( this );
            $loan.find( ':input' ).off( 'input.loan' ).on( 'input.loan', function () {
                solveLoan( $loan, $( this ) );
            } );
            updateLoanReadout( $loan );      // initial advisory, before any edit
        } );
    }

    // ----- VehicleFinanceCalculator: keep a loan's price / down / monthly consistent -----
    // For a LOAN, price, down, and monthly are locked by amortization at the assumed auto-loan rate/term
    // (carried on the form). Editing the price or the down fills the monthly; editing the monthly fills
    // the down (price is the anchor). Cash and lease do nothing here (a lease's payments are not
    // amortization-linked). Bound directly on the fields, so the filled value is set before the form's
    // (change-driven) autosave serializes; setting `.val()` fires no event, so the pair does not loop.

    // The principal a `payment`/month amortizes over `months` at monthly `rate` (mirror of present_value).
    function presentValue( payment, months, rate ) {
        if ( months <= 0 ) { return 0; }
        if ( rate === 0 ) { return payment * months; }
        return payment * ( 1 - Math.pow( 1 + rate, -months ) ) / rate;
    }

    // Whether the checked method carries the form's finances marker (the loan option) -- so the JS gates
    // the amortization on financing without naming the method.
    function financesSelected( $form ) {
        return $form.find( classSelector( C.SWITCH_CONTROL_CLASS ) ).filter( ':checked' )
            .closest( '[' + dataAttr( C.VEHICLE_FINANCES_DATA_ATTR ) + ']' ).length > 0;
    }

    function financeRate( $form ) {
        return ( parseFloat( $form.attr( dataAttr( C.VEHICLE_APR_DATA_ATTR ) ) ) || 0 ) / 100 / 12;
    }

    function financeTerm( $form ) {
        return parseInt( $form.attr( dataAttr( C.VEHICLE_TERM_DATA_ATTR ) ), 10 ) || 0;
    }

    function setMoneyField( $field, amount ) {
        if ( !( amount >= 0 ) ) { return; }              // guard a null/NaN from a degenerate amortization
        $field.val( groupedThousands( String( Math.round( amount ) ) ) );
    }

    // Editing the price or the down fills the monthly: amortize (price - down) over the assumed term.
    function fillVehicleMonthly( $form ) {
        if ( !financesSelected( $form ) ) { return; }
        const term  = financeTerm( $form );
        const price = parseAmount( $form.find( classSelector( C.VEHICLE_PRICE_CLASS ) ).val() );
        if ( !( price > 0 ) || !( term > 0 ) ) { return; }
        const down     = parseAmount( $form.find( classSelector( C.VEHICLE_DOWN_CLASS ) ).val() ) || 0;
        const financed = Math.max( price - down, 0 );
        setMoneyField( $form.find( classSelector( C.VEHICLE_MONTHLY_CLASS ) ),
                       paymentForMonths( financed, term, financeRate( $form ) ) );
    }

    // Editing the monthly fills the down: the price less what that payment finances, clamped to
    // [0, price] (a payment too big to be a loan on this car pins the down at zero or the whole price).
    function fillVehicleDown( $form ) {
        if ( !financesSelected( $form ) ) { return; }
        const term    = financeTerm( $form );
        const price   = parseAmount( $form.find( classSelector( C.VEHICLE_PRICE_CLASS ) ).val() );
        const monthly = parseAmount( $form.find( classSelector( C.VEHICLE_MONTHLY_CLASS ) ).val() );
        if ( !( price > 0 ) || !( term > 0 ) || !( monthly > 0 ) ) { return; }
        const financed = presentValue( monthly, term, financeRate( $form ) );
        const down     = Math.min( Math.max( price - financed, 0 ), price );
        setMoneyField( $form.find( classSelector( C.VEHICLE_DOWN_CLASS ) ), down );
    }

    // A starting down payment for a financed vehicle: a typical fraction of the price, which doubles as
    // rolling the outgoing car's trade-in into the purchase. The engine keeps the down a constant fraction
    // of each inflating replacement price, so this one figure tracks the whole horizon. Seeded ONLY when the
    // down is empty (a user's own figure is never overwritten) and rounded up to the nearest $1,000, so it
    // reads as a round starting point to adjust rather than a derived-looking number.
    const DOWN_PAYMENT_SEED_RATE = 0.12;   // mid the 10-15% band; near a ~10-year trade-in fraction
    function seedVehicleDownPayment( $form ) {
        if ( !financesSelected( $form ) ) { return; }
        const $down = $form.find( classSelector( C.VEHICLE_DOWN_CLASS ) );
        if ( ( $down.val() || '' ).trim() !== '' ) { return; }   // only when empty; never clobber a set value
        const price = parseAmount( $form.find( classSelector( C.VEHICLE_PRICE_CLASS ) ).val() );
        if ( !( price > 0 ) ) { return; }
        setMoneyField( $down, Math.ceil( price * DOWN_PAYMENT_SEED_RATE / 1000 ) * 1000 );
    }

    function enhanceVehicleFinance( $scope ) {
        // Bound on `input` (not `change` like the sibling enhancers) so the mirror fills live as the user
        // types; the `change`-driven autosave then serializes the already-filled field. The empty-down seed
        // runs on `change` -- a committed price, or a switch to LOAN -- so it reads a complete price and
        // lands just before that same change's autosave persists it.
        ( $scope || $( document.body ) ).find( classSelector( C.VEHICLE_FINANCE_CLASS ) ).each( function () {
            const $form       = $( this );
            const priceOrDown = classSelector( C.VEHICLE_PRICE_CLASS ) + ',' + classSelector( C.VEHICLE_DOWN_CLASS );
            $form.find( priceOrDown ).off( 'input.vehicleFinance' )
                .on( 'input.vehicleFinance', function () { fillVehicleMonthly( $form ); } );
            $form.find( classSelector( C.VEHICLE_PRICE_CLASS ) ).off( 'change.vehicleFinance' )
                .on( 'change.vehicleFinance', function () { seedVehicleDownPayment( $form ); fillVehicleMonthly( $form ); } );
            $form.find( classSelector( C.VEHICLE_MONTHLY_CLASS ) ).off( 'input.vehicleFinance' )
                .on( 'input.vehicleFinance', function () { fillVehicleDown( $form ); } );
            $form.find( classSelector( C.SWITCH_CONTROL_CLASS ) ).off( 'change.vehicleFinance' )
                .on( 'change.vehicleFinance', function () { seedVehicleDownPayment( $form ); fillVehicleMonthly( $form ); } );
        } );
    }

    // ----- New scenario, Copy card: reflect the chosen source's component names -----
    // The "copy from" select carries each source scenario's Plans/Assumptions labels per option; show the
    // chosen source's in two spans so the user sees what is being copied/reused. Display-only.

    function reflectCopySource( $select ) {
        const $option = $select.find( 'option:selected' );
        const $form   = $select.closest( 'form' );
        $form.find( classSelector( C.COPY_PLANS_LABEL_CLASS ) )
            .text( $option.attr( dataAttr( C.COPY_SOURCE_PLANS_DATA_ATTR ) ) || '' );
        $form.find( classSelector( C.COPY_ASSUMPTIONS_LABEL_CLASS ) )
            .text( $option.attr( dataAttr( C.COPY_SOURCE_ASSUMPTIONS_DATA_ATTR ) ) || '' );
    }

    function enhanceCopySource( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.COPY_SOURCE_CLASS ) )
            .off( 'change.copySource' )
            .on( 'change.copySource', function () { reflectCopySource( $( this ) ); } )
            .each( function () { reflectCopySource( $( this ) ); } );   // reflect on load
    }

    // ----- New scenario, Pair card: filter Assumptions to a not-yet-used combination -----
    // Each Plans option carries the Assumptions uuids it may still pair with (a comma-separated data
    // attribute); show only those in the Assumptions select. The select is rebuilt to just the allowed
    // options (rather than toggling `hidden`, which Safari ignores for `<option>`), keeping the current
    // choice when it survives. Display-only -- the server re-validates every pairing.

    function filterPairAssumptions( $select ) {
        const allowed = ( $select.find( 'option:selected' ).attr( dataAttr( C.PAIR_AVAILABLE_DATA_ATTR ) ) || '' )
            .split( ',' ).filter( Boolean );
        const assumptions = $select.closest( 'form' ).find( classSelector( C.PAIR_ASSUMPTIONS_CLASS ) )[ 0 ];
        if ( !assumptions ) { return; }
        if ( !assumptions._allOptions ) {                  // cache the full set once, to rebuild from
            assumptions._allOptions = Array.prototype.map.call(
                assumptions.options, function ( option ) {
                    return { value: option.value, label: option.textContent }; } );
        }
        const selected = assumptions.value;
        assumptions.innerHTML = '';
        assumptions._allOptions.forEach( function ( option ) {
            if ( allowed.indexOf( option.value ) === -1 ) { return; }
            const element   = document.createElement( 'option' );
            element.value   = option.value;
            element.text    = option.label;
            element.selected = ( option.value === selected );
            assumptions.appendChild( element );
        } );
    }

    function enhancePairCombine( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.PAIR_PLANS_CLASS ) )
            .off( 'change.pairCombine' )
            .on( 'change.pairCombine', function () { filterPairAssumptions( $( this ) ); } )
            .each( function () { filterPairAssumptions( $( this ) ); } );   // filter on load
    }

    // A durable expense's item calculator: count x cost-each / lifespan-years is the annualized amount,
    // which fills both the amount target(s) and the "per year" readout. Field names are stable
    // (count_/cost_/lifespan_), so the panel's inputs are found by name. The amount stays authoritative
    // (server recomputes on save); this fill is a live preview.
    function calcNumber( $panel, selector ) {
        return parseAmount( $panel.find( selector ).val() ) || 0;
    }

    // A calculator's parts (toggle, panel, target[s]) are linked by a shared data-calc id, so its panel
    // may live anywhere -- a full-width detail row, or inline beside the amount -- not only within a
    // common ancestor. `calcById` selects a part by class + that id.
    function calcById( id, selector ) {
        return $( selector + '[' + dataAttr( C.CALC_DATA_ATTR ) + '="' + id + '"]' );
    }

    function autofillOn( id ) {
        return calcById( id, classSelector( C.CALC_AUTOFILL_CLASS ) ).prop( 'checked' );
    }

    // React to any calculator input -- including its Auto fill checkbox, which lives in the same panel.
    // The readout always previews the estimate; the amount target(s) fill from it only while Auto fill is
    // checked, so an unchecked calculator is a reference the user can hand-tune the bands against without
    // it clobbering their edits (and ticking it back on applies the current estimate). Both readout and
    // target are thousands-grouped, so the live preview reads the same as a saved-and-reloaded amount.
    function updateCalculator( id ) {
        const $panel   = calcById( id, classSelector( C.CALC_PANEL_CLASS ) );
        const count    = calcNumber( $panel, '[name^="count_"]' );
        const cost     = calcNumber( $panel, '[name^="cost_"]' );
        const lifespan = calcNumber( $panel, '[name^="lifespan_"]' ) || 1;
        const annual   = Math.round( ( count * cost ) / lifespan );
        $panel.find( classSelector( C.CALC_READOUT_CLASS ) ).text( groupedThousands( annual ) );
        if ( ! autofillOn( id ) ) {
            return;
        }
        const $targets = calcById( id, classSelector( C.CALC_TARGET_CLASS ) );
        $targets.val( annual ? groupedThousands( annual ) : '' );
        // A flat fill clears the recurring row's change arrows; a no-op on the single-Default property
        // table, whose row carries no span-amount cells.
        updateSpanTrends( $targets.first().closest( 'tr' ) );
    }

    // Apply a calculator's fill when one of its inputs (or its Auto fill checkbox) is about to be saved.
    // A programmatic .val() emits no change of its own, so the fill must run BEFORE the form serializes --
    // like syncField below -- otherwise re-checking Auto fill would persist the pre-fill values. A no-op
    // for any field outside a calculator panel.
    function applyCalculatorFill( $field ) {
        const $panel = $field.closest( classSelector( C.CALC_PANEL_CLASS ) );
        if ( $panel.length ) {
            updateCalculator( $panel.attr( dataAttr( C.CALC_DATA_ATTR ) ) );
        }
    }

    // The recurring-expenses table flags each amount that differs from the previous age span (a tinted
    // cell plus an up/down arrow), so what changes with age is scannable. The server renders the flags;
    // this recomputes a row live as one of its amounts is typed, since the pane saves silently and does
    // not re-render. It mirrors the server exactly: the first span is the baseline, each amount is
    // compared to the one on its left, and a blank amount reads as 0 (as it saves).
    function updateSpanTrends( $row ) {
        let previous = null;
        $row.find( classSelector( C.SPAN_AMOUNT_CLASS ) ).each( function ( index ) {
            const amount    = parseAmount( this.value ) || 0;
            const changed   = index > 0 && amount !== previous;
            const direction = ! changed ? null : ( amount > previous ? 'up' : 'down' );
            setSpanTrend( $( this ), changed, direction );
            previous = amount;
        } );
    }

    // Apply (or clear) a cell's changed styling: tint the money control (a class on the cell) and show
    // the matching arrow -- hidden when unchanged, so every cell keeps the same width and the number
    // column stays aligned.
    function setSpanTrend( $input, changed, direction ) {
        const $cell = $input.closest( 'td' );
        $cell.toggleClass( C.SPAN_CHANGED_CLASS, changed );
        if ( changed ) { $cell.attr( 'title', C.SPAN_CHANGED_TITLE ); }
        else           { $cell.removeAttr( 'title' ); }
        $cell.find( classSelector( C.SPAN_TREND_CLASS ) )
            .toggleClass( 'invisible', ! changed )
            .text( direction === 'up' ? C.SPAN_TREND_UP : C.SPAN_TREND_DOWN );
    }

    // Flag each per-property override cell in a row against the row's current Default: a filled cell
    // whose amount departs from the Default is highlighted; a blank cell inherits the Default, so it is
    // never flagged. The pane saves silently, so this keeps the highlight current client-side as the
    // Default or an override is typed.
    function flagPropertyOverrides( $row ) {
        const base = parseAmount( $row.find( classSelector( C.PROPERTY_DEFAULT_CLASS ) ).val() ) || 0;
        $row.find( classSelector( C.PROPERTY_OVERRIDE_CLASS ) ).each( function () {
            const raw     = ( this.value || '' ).trim();
            const differs = raw !== '' && ( parseAmount( raw ) || 0 ) !== base;
            const $cell   = $( this ).closest( 'td' );
            $cell.toggleClass( C.PROPERTY_DIFFERS_CLASS, differs );
            if ( differs ) { $cell.attr( 'title', C.PROPERTY_DIFFERS_TITLE ); }
            else           { $cell.removeAttr( 'title' ); }
        } );
    }

    $( function () {
        const autosaveForm = 'form' + classSelector( C.AUTOSAVE_CLASS );
        // The age/date sync must mutate the sibling field BEFORE the form is serialized, so it runs
        // first in this one handler rather than relying on separate-handler registration order.
        $( 'body' ).on( 'change', autosaveForm + ' :input', function () {
            const $field = $( this );
            // The disclosure toggle is a UI-only control (no name, nothing to persist): opening a block
            // saves nothing, and its own handler saves on clear. Skip it, or the save's re-render would
            // fight the open it just triggered.
            if ( $field.hasClass( C.OPTIONAL_TOGGLE_CLASS ) ) { return; }
            syncField( $field );
            if ( pairMidEntry( $field ) ) { return; }   // person mid-entry: defer until the pair is whole
            applyCalculatorFill( $field );              // a calculator fill must land before the serialize
            saveForm( $field.closest( 'form' ) );
        } );
        // Enter (or any submit) routes through the same silent save, never a full-page POST.
        $( 'body' ).on( 'submit', autosaveForm, function ( event ) {
            event.preventDefault();
            saveForm( $( this ) );
        } );
        // Inline rename: clear the "name already in use" warning as soon as the user edits, so a valid
        // save need not re-render the field (which would steal focus). The server only re-renders the
        // pane on a genuine conflict.
        $( 'body' ).on( 'input', '.js-rename.is-invalid', function () {
            $( this ).removeClass( 'is-invalid' ).siblings( '.invalid-feedback' ).remove();
        } );

        // Draw-order reorder (Cash Plan): the up/down buttons move a row within its list and save.
        // Each row carries a hidden draw_order input, so the form then serializes the classes in the
        // new priority order; re-rank the badges so the numbering matches. No-op at the list ends.
        $( 'body' ).on( 'click', '.js-draw-up, .js-draw-down', function () {
            const $li = $( this ).closest( 'li' );
            if ( $( this ).hasClass( 'js-draw-up' ) ) { $li.prev( 'li' ).before( $li ); }
            else                                      { $li.next( 'li' ).after( $li ); }
            reRankDraw( $li.closest( 'ul' ) );
            saveForm( $li.closest( 'form' ) );
        } );

        // Keep / draw again toggles a source in place within the one list. Retaining enables the row's
        // `retained` input (so the form posts it, and materialization drops it before the engine) and
        // mutes the row: its rank clears, the KEPT badge shows, and exclude swaps to restore. Drawing
        // again reverses it. The rank badges number the enabled rows only, so a retained row shows none
        // and the numbering stays true to draw priority. Toggling fires no `change`, so save explicitly.
        function reRankDraw( $drawList ) {
            let rank = 0;
            $drawList.find( '.js-draw-source' ).each( function () {
                const $rank = $( this ).find( '.js-draw-rank' );
                if ( $( this ).hasClass( 'js-draw-retained' ) ) { $rank.text( '' ); }
                else { rank += 1; $rank.text( rank ); }
            } );
        }
        function setDrawSourceRetained( button, retained ) {
            const $li = $( button ).closest( 'li' );
            $li.toggleClass( 'js-draw-retained', retained );
            $li.find( 'input[name="retained"]' ).prop( 'disabled', ! retained );
            $li.find( '.js-draw-rank' ).toggleClass( 'd-none', retained );
            $li.find( '.js-draw-kept' ).toggleClass( 'd-none', ! retained );
            $li.find( '.js-draw-disable' ).toggleClass( 'd-none', retained );
            $li.find( '.js-draw-enable' ).toggleClass( 'd-none', ! retained );
            // Muted while retained or not yet held; a held source de-mutes when drawn again.
            $li.find( '.js-draw-label' ).toggleClass( 'text-muted', retained || ! $li.hasClass( 'js-draw-held' ) );
            reRankDraw( $li.closest( 'ul' ) );
            saveForm( $li.closest( 'form' ) );
        }
        $( 'body' ).on( 'click', '.js-draw-disable', function () { setDrawSourceRetained( this, true  ); } );
        $( 'body' ).on( 'click', '.js-draw-enable',  function () { setDrawSourceRetained( this, false ); } );

        // Sweep table (Cash Plan): add clones the first row (cleared) so a new holding/weight pair
        // joins the form; remove drops a row, but the last row is cleared rather than removed so the
        // table always keeps one editable line. Either way, persist -- clearing/removing fires no
        // `change`, so the autosave must be triggered explicitly.
        $( 'body' ).on( 'click', '.js-sweep-add', function () {
            const $table = $( this ).closest( 'form' ).find( '.js-sweep-table' );
            const $row   = $table.find( '.js-sweep-row' ).first().clone();
            $row.find( 'select' ).val( '' );
            $row.find( 'input[name="sweep_weight"]' ).val( '' );
            $table.find( 'tbody' ).append( $row );
            $row.find( 'select' ).trigger( 'focus' );
        } );
        $( 'body' ).on( 'click', '.js-sweep-remove', function () {
            const $row  = $( this ).closest( '.js-sweep-row' );
            const $form = $row.closest( 'form' );
            if ( $row.siblings( '.js-sweep-row' ).length ) { $row.remove(); }
            else { $row.find( 'select, input' ).val( '' ); }
            saveForm( $form );
        } );

        // Rowset add: clone the hidden <template> prototype into the row container and focus the new row's
        // first field. The clone's repeated-name inputs serialize with the rest, so the getlist form reads
        // the new row on the next save. The prototype (inside <template>) is inert, so it never submits.
        $( 'body' ).on( 'click', classSelector( C.ROWSET_ADD_CLASS ), function () {
            const $rowset  = $( this ).closest( 'form' ).find( classSelector( C.ROWSET_CLASS ) );
            const template = $rowset.find( classSelector( C.ROWSET_TEMPLATE_CLASS ) ).get( 0 );
            if ( ! template ) { return; }
            const $row = $( template.content.firstElementChild.cloneNode( true ) );
            $rowset.append( $row );
            enhanceMoneyInputs( $row );                  // group any money cell the new row carries
            $row.find( ':input:not([type=hidden])' ).first().trigger( 'focus' );   // skip a leading hidden handle
        } );
        // Rowset remove: drop the row and persist -- the removed row's inputs leave the serialization, so
        // the getlist form rebuilds the set without it (removal fires no `change`, hence the explicit save).
        $( 'body' ).on( 'click', classSelector( C.ROWSET_REMOVE_CLASS ), function () {
            const $row  = $( this ).closest( classSelector( C.ROWSET_ROW_CLASS ) );
            const $form = $row.closest( 'form' + classSelector( C.AUTOSAVE_CLASS ) );
            $row.remove();
            if ( $form.length ) { saveForm( $form ); }
        } );

        // Reveal an optional block; land the caret on its first field so the user can type straight in.
        $( 'body' ).on( 'click', classSelector( C.OPTIONAL_ADD_CLASS ), function () {
            const $section = $( this ).closest( classSelector( C.OPTIONAL_CLASS ) );
            setOptionalOpen( $section, true );
            optionalParts( $section ).body.find( ':input' ).first().trigger( 'focus' );
        } );
        // Dismiss an optional block via its remove button: clear + collapse (see clearAndCollapseOptional).
        $( 'body' ).on( 'click', classSelector( C.OPTIONAL_REMOVE_CLASS ), function () {
            clearAndCollapseOptional( $( this ).closest( classSelector( C.OPTIONAL_CLASS ) ) );
        } );
        // The checkbox style of the same disclosure: checking asks to open the block (caret on its first
        // field); unchecking clears + collapses it, exactly like the remove button.
        $( 'body' ).on( 'change', classSelector( C.OPTIONAL_TOGGLE_CLASS ), function () {
            const $section = $( this ).closest( classSelector( C.OPTIONAL_CLASS ) );
            if ( $( this ).prop( 'checked' ) ) {
                setOptionalOpen( $section, true );
                optionalParts( $section ).body.find( ':input' ).first().trigger( 'focus' );
            } else {
                clearAndCollapseOptional( $section );
            }
        } );

        // Flip a switch to the chosen case as its control changes.
        $( 'body' ).on( 'change', classSelector( C.SWITCH_CLASS ) + ' ' + classSelector( C.SWITCH_CONTROL_CLASS ),
            function () { applySwitch( $( this ).closest( classSelector( C.SWITCH_CLASS ) ) ); } );

        // Reveal the residence-only sale option (Sell a property) as the property picker changes -- shown
        // only while the chosen property is the primary residence.
        $( 'body' ).on( 'change', '[' + dataAttr( C.RESIDENCE_HANDLES_DATA_ATTR ) + '] select', function () {
            applyResidenceOptions( $( this ).closest( '[' + dataAttr( C.RESIDENCE_HANDLES_DATA_ATTR ) + ']' ) );
        } );

        // Group a money input's thousands as it is typed (money fields are text inputs, so a comma is a
        // valid character); the MoneyField strips it back to a bare number on the server.
        $( 'body' ).on( 'input', classSelector( C.MONEY_INPUT_CLASS ), function () {
            groupMoneyInput( this );
        } );

        // Refresh a credit card's advisory readout as its mode or inputs change.
        $( 'body' ).on( 'input change', classSelector( C.CREDIT_CARD_CLASS ) + ' :input',
            function () { updateCard( $( this ).closest( classSelector( C.CREDIT_CARD_CLASS ) ) ); } );

        // Delete a recurring-expenses column: stamp its span index into the form's hidden field, then
        // save -- the server drops the span and re-renders the table.
        $( 'body' ).on( 'click', classSelector( C.RECURRING_DELETE_CLASS ), function () {
            const $form = $( this ).closest( 'form' + classSelector( C.AUTOSAVE_CLASS ) );
            $form.find( 'input[name="delete_span"]' ).val( $( this ).data( 'span' ) );
            saveForm( $form );
        } );

        // Reveal/hide a durable's calculator panel, matched to the toggle by its data-calc id.
        $( 'body' ).on( 'click', classSelector( C.CALC_TOGGLE_CLASS ), function () {
            const $panel = calcById( $( this ).attr( dataAttr( C.CALC_DATA_ATTR ) ),
                                     classSelector( C.CALC_PANEL_CLASS ) );
            $panel.prop( 'hidden', ! $panel.prop( 'hidden' ) );
        } );

        // Live-preview a calculator as its inputs (or its Auto fill checkbox) change: recompute the
        // readout and, while Auto fill is on, fill the amount target(s). This covers the `input` phase;
        // the matching `change` runs through the autosave handler above (applyCalculatorFill), which fills
        // once more just before serializing so the saved values are the filled ones -- not dependent on
        // `input` firing before `change`.
        $( 'body' ).on( 'input', classSelector( C.CALC_PANEL_CLASS ) + ' :input', function () {
            updateCalculator( $( this ).closest( classSelector( C.CALC_PANEL_CLASS ) )
                .attr( dataAttr( C.CALC_DATA_ATTR ) ) );
        } );

        // Re-flag a recurring row's changed amounts as one of them is typed, so the highlight tracks the
        // edit without waiting for a re-render (the pane saves silently).
        $( 'body' ).on( 'input change', classSelector( C.SPAN_AMOUNT_CLASS ), function () {
            updateSpanTrends( $( this ).closest( 'tr' ) );
        } );

        // Mirror a property-expense row's Default into its blank per-property cells' placeholders as it
        // is typed, so a changed default is visible where a cell falls back to it. The pane saves
        // silently and does not re-render these placeholders, so this keeps them current client-side.
        // A single-property matrix collapses the Default column, so its row has no override cells and
        // this is a harmless no-op.
        $( 'body' ).on( 'input change', classSelector( C.PROPERTY_DEFAULT_CLASS ), function () {
            const $row = $( this ).closest( 'tr' );
            const placeholder = ( $( this ).val() || '' ).trim() || '0';
            $row.find( classSelector( C.PROPERTY_OVERRIDE_CLASS ) ).attr( 'placeholder', placeholder );
            flagPropertyOverrides( $row );   // a changed Default can flip which overrides now differ
        } );

        // Re-flag a row's overrides as one of them is typed, so the highlight tracks the edit.
        $( 'body' ).on( 'input change', classSelector( C.PROPERTY_OVERRIDE_CLASS ), function () {
            flagPropertyOverrides( $( this ).closest( 'tr' ) );
        } );

        // Pickers, optional-section state, and switch state attach to concrete elements, so (unlike
        // the delegated handlers above) they must be (re)applied to whatever DOM is present: once
        // now, and again after each antinode render for swapped-in content. Pickers are also torn
        // down before a subtree is removed. AN is absent under the test harness, so guard it.
        enhanceDates( $( document.body ) );
        enhanceOptionalSections( $( document.body ) );
        enhanceSwitches( $( document.body ) );
        enhanceResidenceOptions( $( document.body ) );
        enhanceCreditCards( $( document.body ) );
        enhanceLoans( $( document.body ) );
        enhanceVehicleFinance( $( document.body ) );
        enhanceStateAutofill( $( document.body ) );
        enhanceCopySource( $( document.body ) );
        enhancePairCombine( $( document.body ) );
        enhanceMoneyInputs( $( document.body ) );
        neutralizeReadOnly( $( document.body ) );       // last: disable the enhanced controls if read-only
        if ( window.AN ) {
            AN.addAfterAsyncRenderFunction( function () {
                enhanceDates( $( document.body ) );
                enhanceOptionalSections( $( document.body ) );
                enhanceSwitches( $( document.body ) );
                enhanceResidenceOptions( $( document.body ) );
                enhanceCreditCards( $( document.body ) );
                enhanceLoans( $( document.body ) );
                enhanceVehicleFinance( $( document.body ) );
                enhanceStateAutofill( $( document.body ) );
                enhanceCopySource( $( document.body ) );
                enhancePairCombine( $( document.body ) );
                enhanceMoneyInputs( $( document.body ) );
                neutralizeReadOnly( $( document.body ) );
            } );
            AN.addBeforeContentRemovalFunction( function ( $subtree ) { destroyDates( $subtree ); } );
        }
    } );

    return {
        syncField               : syncField,
        saveForm                : saveForm,
        enhanceDates            : enhanceDates,
        enhanceOptionalSections : enhanceOptionalSections,
        enhanceSwitches         : enhanceSwitches,
        enhanceResidenceOptions : enhanceResidenceOptions,
        enhanceCreditCards      : enhanceCreditCards,
        selectLoanSink          : selectLoanSink,   // exposed for unit testing (pure sink-selection logic)
    };
} )();

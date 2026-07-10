// Client-side behaviors for the inputs section. Two concerns live here:
//
//   AgeDateSync - the income table's convenience age columns. The date is canonical (see
//     ucfp/inputs/income.py); the age beside it is kept in lockstep client-side so the server only
//     ever reads dates. A field's birthdate is either baked in (entitlement rows) or resolved live
//     from the row's chosen subject against a handle->ISO map on the table container.
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

    // ----- AgeDateSync: keep each age column in step with its canonical date -----

    // The handle->ISO-date map lives on the nearest container that carries it (the income table),
    // so the lookup is id-free and works for any date/age field nested inside such a container.
    function birthdateMap( $field ) {
        const $container = $field.closest( '[' + dataAttr( C.BIRTHDATES_DATA_ATTR ) + ']' );
        try { return JSON.parse( $container.attr( dataAttr( C.BIRTHDATES_DATA_ATTR ) ) || '{}' ); }
        catch ( e ) { return {}; }
    }

    // A date/age field's birthdate is either baked in (entitlement rows) or resolved live from the
    // row's currently chosen subject (general rows).
    function birthdateFor( $field ) {
        const fixed = $field.attr( dataAttr( C.BIRTHDATE_DATA_ATTR ) );
        if ( fixed ) { return fixed; }
        const subjectId = $field.attr( dataAttr( C.SUBJECT_FIELD_DATA_ATTR ) );
        if ( ! subjectId ) { return null; }
        return birthdateMap( $field )[ $( '#' + subjectId ).val() ] || null;
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
            $( '#' + $age.attr( dataAttr( C.DATE_FIELD_DATA_ATTR ) ) ).val( atAge( birth, age ) );
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

    // ----- AutoSave: silent background persistence -----

    function saveForm( $form ) {
        AN.post( $form.attr( 'action' ), $form.serialize(), { suppressLoader: true } );
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

    // Past-facing contexts cannot run beyond today and open on the decade-of-years view (startView
    // 2), so reaching a far year is a couple of clicks rather than months of paging; forward-facing
    // dates open on the normal day view but may still be typed or header-zoomed to a distant year.
    function datepickerOptions( context ) {
        if ( context === C.DATE_CONTEXT_BIRTHDATE || context === C.DATE_CONTEXT_PAST ) {
            return Object.assign( {}, DATEPICKER_BASE, { endDate : '+0d', startView : 2 } );
        }
        return Object.assign( {}, DATEPICKER_BASE );
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
        };
    }

    function setOptionalOpen( $section, open ) {
        const parts = optionalParts( $section );
        parts.body.prop( 'hidden', ! open );
        parts.add.prop( 'hidden', open );
        parts.remove.prop( 'hidden', ! open );
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
            const $section = $( this );
            setOptionalOpen( $section, bodyIsFilled( optionalParts( $section ).body ) );
        } );
    }

    // ----- SwitchGroup: reveal the case block matching a control's value -----
    //
    // A control (radio group or select) inside a `js-switch` wrapper picks which sibling case block
    // shows; the rest hide. Every case renders visible without JS -- the server reads only the fields
    // the chosen case makes relevant -- so this is pure presentation, (re)applied on load and after
    // each render, plus live on the control's change.

    function switchValue( $switch ) {
        const $control = $switch.find( classSelector( C.SWITCH_CONTROL_CLASS ) );
        const $checked = $control.filter( ':radio:checked' );
        return $checked.length ? $checked.val() : $control.not( ':radio' ).val();
    }

    function applySwitch( $switch ) {
        const value = switchValue( $switch );
        $switch.find( '[' + dataAttr( C.SWITCH_CASE_DATA_ATTR ) + ']' ).each( function () {
            const $case = $( this );
            const cases = ( $case.attr( dataAttr( C.SWITCH_CASE_DATA_ATTR ) ) || '' ).split( /\s+/ );
            $case.prop( 'hidden', cases.indexOf( value ) === -1 );
        } );
    }

    function enhanceSwitches( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.SWITCH_CLASS ) )
            .each( function () { applySwitch( $( this ) ); } );
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

    function cardMode( $card ) {
        return $card.find( classSelector( C.SWITCH_CONTROL_CLASS ) ).filter( ':checked' ).val();
    }

    // Months of `payment` to clear `balance` at the card rate, or null when it never does (the
    // payment does not cover the interest) -- the client mirror of common.amortization.periods_to_repay.
    function monthsToClear( balance, payment, rate ) {
        if ( balance <= 0 ) { return 0; }
        if ( rate > 0 && payment <= balance * rate ) { return null; }
        let remaining = balance, months = 0;
        while ( remaining > 0 && months < 1200 ) {
            months += 1;
            const payoff = remaining + remaining * rate;
            if ( payment >= payoff ) { return months; }
            remaining = payoff - payment;
        }
        return months < 1200 ? months : null;
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
        const mode = cardMode( $card );
        const monthly = function () {
            return parseFloat( $card.find( classSelector( C.CREDIT_CARD_MONTHLY_CLASS ) ).val() );
        };
        const targetMonths = function () {
            return monthsUntil( $card.find( classSelector( C.CREDIT_CARD_DATE_CLASS ) ).val() );
        };
        // Carrying it (the default) and a lump payoff both cost only the interest each month.
        if ( mode === 'carry' || mode === 'LUMP' || !mode ) {
            return 'Carrying it costs about ' + money( balance * rate ) + '/month in interest.';
        }
        if ( mode === 'MONTHLY' ) {
            const payment = monthly();
            if ( !( payment > 0 ) ) { return ''; }
            const months = monthsToClear( balance, payment, rate );
            return months === null
                ? 'That won\'t cover the interest, so the balance never clears.'
                : 'Clears in ' + describeMonths( months ) + '.';
        }
        if ( mode === 'BY_DATE' ) {
            const months = targetMonths();
            if ( !months || months <= 0 ) { return ''; }
            return 'That needs about ' + money( paymentForMonths( balance, months, rate ) ) + '/month.';
        }
        if ( mode === 'COMBO' ) {
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

    // ----- LoanCalculator: a live, advisory monthly-payment estimate per loan -----
    // Display-only. As a loan's rate/term/extra change, write the level payment its terms imply into
    // its readout, reusing the amortization mirrors above. Materialization is authoritative.

    function loanField( $loan, cls ) {
        return parseFloat( $loan.find( classSelector( cls ) ).val() );
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

    function loanReadout( $loan ) {
        const balance = parseFloat( $loan.attr( dataAttr( C.LOAN_BALANCE_DATA_ATTR ) ) ) || 0;
        const ratePercent = loanField( $loan, C.LOAN_RATE_CLASS );
        const months = loanField( $loan, C.LOAN_TERM_CLASS );
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

    function updateLoan( $loan ) {
        $loan.find( classSelector( C.LOAN_READOUT_CLASS ) ).first().text( loanReadout( $loan ) );
    }

    function enhanceLoans( $scope ) {
        ( $scope || $( document.body ) ).find( classSelector( C.LOAN_CLASS ) )
            .each( function () { updateLoan( $( this ) ); } );
    }

    // A durable expense's item calculator: count x cost-each / lifespan-years is the annualized amount,
    // which fills both the amount target(s) and the "per year" readout. Field names are stable
    // (count_/cost_/lifespan_), so the panel's inputs are found by name. The amount stays authoritative
    // (server recomputes on save); this fill is a live preview.
    function calcNumber( $panel, selector ) {
        return parseFloat( $panel.find( selector ).val() ) || 0;
    }

    function updateCalculator( $calc ) {
        const $panel   = $calc.find( classSelector( C.CALC_PANEL_CLASS ) );
        const count    = calcNumber( $panel, '[name^="count_"]' );
        const cost     = calcNumber( $panel, '[name^="cost_"]' );
        const lifespan = calcNumber( $panel, '[name^="lifespan_"]' ) || 1;
        const annual   = Math.round( ( count * cost ) / lifespan );
        // The readout mirrors the amount target verbatim (both bare whole dollars), so it matches the
        // server's initial pre-JS render rather than reformatting on the first edit.
        $calc.find( classSelector( C.CALC_TARGET_CLASS ) ).val( annual ? annual : '' );
        $calc.find( classSelector( C.CALC_READOUT_CLASS ) ).text( annual );
    }

    // The vehicle running-costs table: each row's Total = its per-car amount x the shared car count
    // (from the sibling purchase pane), recomputed live and shown at the row's cadence. Display-only --
    // materialization scales by num_cars authoritatively on save. A dash shows until both are set.
    function updateVehicleTotals() {
        const numCars = parseFloat( $( classSelector( C.VEHICLE_NUM_CARS_CLASS ) ).val() ) || 0;
        $( classSelector( C.VEHICLE_COSTS_CLASS ) ).find( classSelector( C.VEHICLE_PERCAR_CLASS ) )
            .each( function () {
                const perCar = parseFloat( $( this ).val() );
                const total  = ( numCars && ! isNaN( perCar ) )
                    ? '$' + Math.round( perCar * numCars ) : '—';
                $( this ).closest( 'tr' ).find( classSelector( C.VEHICLE_TOTAL_CLASS ) ).text( total );
            } );
    }

    $( function () {
        const autosaveForm = 'form' + classSelector( C.AUTOSAVE_CLASS );
        // The age/date sync must mutate the sibling field BEFORE the form is serialized, so it runs
        // first in this one handler rather than relying on separate-handler registration order.
        $( 'body' ).on( 'change', autosaveForm + ' :input', function () {
            const $field = $( this );
            syncField( $field );
            saveForm( $field.closest( 'form' ) );
        } );
        // Enter (or any submit) routes through the same silent save, never a full-page POST.
        $( 'body' ).on( 'submit', autosaveForm, function ( event ) {
            event.preventDefault();
            saveForm( $( this ) );
        } );

        // A form marked data-confirm asks before it submits -- the guard for destructive actions
        // (deleting a plans/assumptions set). Cancelling stops the submission.
        $( 'body' ).on( 'submit', 'form[data-confirm]', function ( event ) {
            if ( ! window.confirm( $( this ).data( 'confirm' ) ) ) { event.preventDefault(); }
        } );

        // Reveal an optional block; land the caret on its first field so the user can type straight in.
        $( 'body' ).on( 'click', classSelector( C.OPTIONAL_ADD_CLASS ), function () {
            const $section = $( this ).closest( classSelector( C.OPTIONAL_CLASS ) );
            setOptionalOpen( $section, true );
            optionalParts( $section ).body.find( ':input' ).first().trigger( 'focus' );
        } );
        // Dismiss an optional block: clear it (so the server reads it as absent) then collapse.
        // Clearing fields programmatically fires no `change`, so inside an autosave form the removal
        // must be persisted explicitly -- otherwise a removed partner would linger until the next edit.
        $( 'body' ).on( 'click', classSelector( C.OPTIONAL_REMOVE_CLASS ), function () {
            const $section = $( this ).closest( classSelector( C.OPTIONAL_CLASS ) );
            optionalParts( $section ).body.find( ':input' )
                .val( '' ).filter( ':checkbox, :radio' ).prop( 'checked', false );
            setOptionalOpen( $section, false );
            const $form = $section.closest( 'form' + classSelector( C.AUTOSAVE_CLASS ) );
            if ( $form.length ) { saveForm( $form ); }
        } );

        // Flip a switch to the chosen case as its control changes.
        $( 'body' ).on( 'change', classSelector( C.SWITCH_CLASS ) + ' ' + classSelector( C.SWITCH_CONTROL_CLASS ),
            function () { applySwitch( $( this ).closest( classSelector( C.SWITCH_CLASS ) ) ); } );

        // Refresh a credit card's advisory readout as its mode or inputs change.
        $( 'body' ).on( 'input change', classSelector( C.CREDIT_CARD_CLASS ) + ' :input',
            function () { updateCard( $( this ).closest( classSelector( C.CREDIT_CARD_CLASS ) ) ); } );

        // Refresh a loan's advisory payment estimate as its rate/term/extra change.
        $( 'body' ).on( 'input change', classSelector( C.LOAN_CLASS ) + ' :input',
            function () { updateLoan( $( this ).closest( classSelector( C.LOAN_CLASS ) ) ); } );

        // Delete a recurring-expenses column: stamp its span index into the form's hidden field, then
        // save -- the server drops the span and re-renders the table.
        $( 'body' ).on( 'click', classSelector( C.RECURRING_DELETE_CLASS ), function () {
            const $form = $( this ).closest( 'form' + classSelector( C.AUTOSAVE_CLASS ) );
            $form.find( 'input[name="delete_span"]' ).val( $( this ).data( 'span' ) );
            saveForm( $form );
        } );

        // Reveal/hide a durable's item calculator panel.
        $( 'body' ).on( 'click', classSelector( C.CALC_TOGGLE_CLASS ), function () {
            const $panel = $( this ).closest( classSelector( C.CALC_CLASS ) )
                .find( classSelector( C.CALC_PANEL_CLASS ) );
            $panel.prop( 'hidden', ! $panel.prop( 'hidden' ) );
        } );

        // Recompute a calculator's total + per-year and fill its amount target(s) as its inputs change.
        $( 'body' ).on( 'input change', classSelector( C.CALC_PANEL_CLASS ) + ' :input', function () {
            updateCalculator( $( this ).closest( classSelector( C.CALC_CLASS ) ) );
        } );

        // Recompute the vehicle running-costs totals as a per-car amount or the shared car count changes.
        $( 'body' ).on( 'input change',
            classSelector( C.VEHICLE_PERCAR_CLASS ) + ', ' + classSelector( C.VEHICLE_NUM_CARS_CLASS ),
            updateVehicleTotals );

        // Mirror a property-expense row's Default into its blank per-property cells' placeholders as it
        // is typed, so a changed default is visible where a cell falls back to it. The pane saves
        // silently and does not re-render these placeholders, so this keeps them current client-side.
        // A single-property matrix collapses the Default column, so its row has no override cells and
        // this is a harmless no-op.
        $( 'body' ).on( 'input change', classSelector( C.PROPERTY_DEFAULT_CLASS ), function () {
            const placeholder = ( $( this ).val() || '' ).trim() || '0';
            $( this ).closest( 'tr' ).find( classSelector( C.PROPERTY_OVERRIDE_CLASS ) )
                .attr( 'placeholder', placeholder );
        } );

        // Pickers, optional-section state, and switch state attach to concrete elements, so (unlike
        // the delegated handlers above) they must be (re)applied to whatever DOM is present: once
        // now, and again after each antinode render for swapped-in content. Pickers are also torn
        // down before a subtree is removed. AN is absent under the test harness, so guard it.
        enhanceDates( $( document.body ) );
        enhanceOptionalSections( $( document.body ) );
        enhanceSwitches( $( document.body ) );
        enhanceCreditCards( $( document.body ) );
        enhanceLoans( $( document.body ) );
        if ( window.AN ) {
            AN.addAfterAsyncRenderFunction( function () {
                enhanceDates( $( document.body ) );
                enhanceOptionalSections( $( document.body ) );
                enhanceSwitches( $( document.body ) );
                enhanceCreditCards( $( document.body ) );
                enhanceLoans( $( document.body ) );
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
        enhanceCreditCards      : enhanceCreditCards,
    };
} )();

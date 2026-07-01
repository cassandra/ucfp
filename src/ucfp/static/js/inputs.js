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
// The first two are wired as delegated handlers on `body`, so they survive an antinode pane swap and
// bind exactly once. All the ids/classes/data-attributes shared with the templates come from
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

        // Pickers attach to concrete elements, so (unlike the delegated handlers above) they must be
        // (re)applied to whatever DOM is present: once now, again after each antinode render for
        // swapped-in inputs, and torn down before a subtree is removed. AN is absent under the test
        // harness, so guard it.
        enhanceDates( $( document.body ) );
        if ( window.AN ) {
            AN.addAfterAsyncRenderFunction( function () { enhanceDates( $( document.body ) ); } );
            AN.addBeforeContentRemovalFunction( function ( $subtree ) { destroyDates( $subtree ); } );
        }
    } );

    return {
        syncField    : syncField,
        saveForm     : saveForm,
        enhanceDates : enhanceDates,
    };
} )();

/* Social Security timing calculator behaviour for the inputs and results pages.

   Loaded globally in the js_before_content bundle (so it runs before page content), it keys off element
   presence and defers all DOM work to ready. Inputs page: show/hide the partner card for a one-person
   household, initialise the year-only birth-year picker, keep the asset-return "above inflation" hints in
   sync, and move focus to the error summary on a failed submit. Results page: move the gold selection when
   a heatmap cell or ranked row is activated (the detail
   swap itself is antinode's; this only tracks the selection), and make the ranked rows keyboard-operable.
   Events are delegated so an antinode detail swap never drops a handler. */
( function ( $ ) {
    'use strict';

    function initHouseholdToggle() {
        var $choice = $( '#household-choice' );
        if ( !$choice.length ) { return; }
        function sync() {
            var couple = $choice.find( 'input:checked' ).val() === 'couple';
            $( '#person-1' ).toggle( couple );
        }
        $choice.on( 'change', sync );
        sync();
    }

    function initYearPickers() {
        if ( !$.fn.datepicker ) { return; }
        $( '.js-year-picker' ).datepicker( {
            format: 'yyyy', minViewMode: 'years', maxViewMode: 'years',
            autoclose: true, startDate: '1900', endDate: new Date()
        } );
    }

    function initReturnHints() {
        // The asset return is a nominal figure, but what the comparison uses is the part *above* inflation
        // (benefits already rise with inflation). Keep that legible and inflation-relative: fill an empty
        // return with the conservative default (inflation + ~2% real); show the real equivalent of what is
        // typed beside the input; and state the default in concrete nominal terms in the help (the bold
        // number IS the value to enter), so nothing reads as a bare "2%" to type into the box.
        var DEFAULT_REAL = 2;   // the conservative safe real return the default targets (see forms.py)
        var $return    = $( '#id_expected_return' );
        var $inflation = $( '#id_inflation' );
        var $hint      = $( '#return-real-hint' );
        var $default   = $( '#return-default' );
        var $note      = $( '#return-default-note' );
        if ( !$return.length || !$inflation.length ) { return; }
        function conservativeNominal( inflation ) {
            return ( inflation + DEFAULT_REAL ).toFixed( 1 );
        }
        function fillIfEmpty() {
            // Only on load and when inflation changes -- never on the return's own input, or clearing it
            // to retype would refill instantly.
            var inflation = parseFloat( $inflation.val() );
            if ( !isNaN( inflation ) && $return.val().trim() === '' ) {
                $return.val( conservativeNominal( inflation ) );
            }
        }
        function refresh() {
            var inflation = parseFloat( $inflation.val() );
            var nominal   = parseFloat( $return.val() );
            if ( $hint.length ) {
                $hint.text( ( isNaN( nominal ) || isNaN( inflation ) ) ? ''
                    : '≈ ' + ( nominal - inflation ).toFixed( 1 ) + '% above inflation' );
            }
            if ( $default.length && !isNaN( inflation ) ) {
                $default.text( conservativeNominal( inflation ) + '%' );          // the number to enter
                if ( $note.length ) {
                    $note.text( ' — roughly ' + DEFAULT_REAL + '% above your ' + inflation + '% inflation' );
                }
            }
        }
        $return.on( 'input', refresh );
        $inflation.on( 'input', function () { fillIfEmpty(); refresh(); } );
        fillIfEmpty();
        refresh();
    }

    function focusErrorSummary() {
        // On a failed submit the page reloads with the summary present; focusing it announces the error to
        // assistive tech and lands the keyboard where the "review the fields" message is.
        var summary = document.getElementById( 'ss-error-summary' );
        if ( summary ) { summary.focus(); }
    }

    function moveSelection( combo ) {
        $( '[data-combo]' ).each( function () {
            $( this ).toggleClass( 'sel', this.dataset.combo === combo );
        } );
    }

    function initSelectionSync() {
        // A ranked row delegates to its matching heatmap cell (the antinode link that swaps the detail),
        // so both surfaces and the fetch stay in sync through one path; keyboard activation mirrors a click.
        $( document ).on( 'click', '.ss-hm-cell', function () { moveSelection( this.dataset.combo ); } );
        $( document ).on( 'click', '.rank-row', function () {
            var cell = document.querySelector( '.ss-hm-cell[data-combo="' + this.dataset.combo + '"]' );
            if ( cell ) { cell.click(); }
        } );
        $( document ).on( 'keydown', '.rank-row', function ( event ) {
            if ( event.key === 'Enter' || event.key === ' ' ) {
                event.preventDefault();
                $( this ).trigger( 'click' );
            }
        } );
    }

    $( function () {
        initHouseholdToggle();
        initYearPickers();
        initReturnHints();
        focusErrorSummary();
        initSelectionSync();
    } );
} )( jQuery );

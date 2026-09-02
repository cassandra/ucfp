/* Social Security timing calculator behaviour for the inputs and results pages.

   Loaded globally in the js_before_content bundle (so it runs before page content), it keys off element
   presence and defers all DOM work to ready. Inputs page: show/hide the partner card for a one-person
   household, initialise the year-only birth-year picker, keep the asset-return "above inflation" hints in
   sync, and move focus to the error summary on a failed submit. Results page: move the gold selection when
   a heatmap cell or ranked row is activated (the detail swap itself is antinode's; this only tracks the
   selection), and make the ranked rows keyboard-operable. The selection listeners are bound directly to
   the (static) cells and rows -- not delegated at document -- because antinode stops the async click from
   bubbling; see initSelectionSync. */
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
        var HIGH_REAL    = 5;   // above ~5% real is beyond even an aggressive long-run estimate -> warn
        var $return    = $( '#id_expected_return' );
        var $inflation = $( '#id_inflation' );
        var $hint      = $( '#return-real-hint' );
        var $warn      = $( '#return-warn' );
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
            var real      = nominal - inflation;
            if ( $hint.length ) {
                $hint.text( ( isNaN( nominal ) || isNaN( inflation ) ) ? ''
                    : '≈ ' + real.toFixed( 1 ) + '% above inflation' );
            }
            if ( $warn.length ) {
                $warn.text( ( !isNaN( real ) && real > HIGH_REAL )
                    ? 'That’s optimistic — even aggressive long-run estimates are around ' + HIGH_REAL
                      + '% above inflation, and money you may spend soon can’t safely earn that much.'
                    : '' );
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

    function bindRankRows() {
        // A ranked row triggers its matching heatmap cell, so both surfaces and the antinode fetch stay in
        // sync. The ranked table is re-rendered on each drill-in (to pull in an out-of-top-10 pick as the
        // 11th row), so its rows are fresh elements each time; the data-sel-bound guard wires each row once
        // and skips ones already bound (e.g. after an unrelated async render like a modal).
        document.querySelectorAll( '.rank-row' ).forEach( function ( row ) {
            if ( row.dataset.selBound ) { return; }
            row.dataset.selBound = '1';
            function activate() {
                var cell = document.querySelector( '.ss-hm-cell[data-combo="' + row.dataset.combo + '"]' );
                if ( cell ) { cell.click(); }
            }
            row.addEventListener( 'click', activate );
            row.addEventListener( 'keydown', function ( event ) {
                if ( event.key === 'Enter' || event.key === ' ' ) {
                    event.preventDefault();
                    activate();
                }
            } );
        } );
    }

    function initSelectionSync() {
        // Direct listeners on the cells, NOT delegated at document: the heatmap cell is an antinode link,
        // and antinode's document-level handling stops the click bubbling, so a delegated handler never
        // sees it (the detail swaps but the gold selection would not move). The heatmap is static (only
        // #ss-detail and #ss-rank swap), so binding the cells once is safe; the ranked rows are re-bound
        // after each swap (see bindRankRows).
        document.querySelectorAll( '.ss-hm-cell' ).forEach( function ( cell ) {
            cell.addEventListener( 'click', function () { moveSelection( cell.dataset.combo ); } );
        } );
        bindRankRows();
        if ( window.AN ) {
            AN.addAfterAsyncRenderFunction( bindRankRows );
        }
    }

    $( function () {
        initHouseholdToggle();
        initYearPickers();
        initReturnHints();
        focusErrorSummary();
        initSelectionSync();
    } );
} )( jQuery );

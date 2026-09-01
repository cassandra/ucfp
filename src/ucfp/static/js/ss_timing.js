/* Social Security timing calculator behaviour for the inputs and results pages.

   Loaded globally in the js_before_content bundle (so it runs before page content), it keys off element
   presence and defers all DOM work to ready. Inputs page: show/hide the partner card for a one-person
   household, initialise the year-only birth-year picker, and move focus to the error summary on a failed
   submit. Results page: move the gold selection when a heatmap cell or ranked row is activated (the detail
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
        focusErrorSummary();
        initSelectionSync();
    } );
} )( jQuery );

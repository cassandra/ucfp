/* Social Security timing results: move the gold selection when a heatmap cell or ranked row is clicked.
   The detail swap itself is antinode's (the cells are data-async links); this only tracks the selection.
   A ranked-row click delegates to its matching heatmap cell so both surfaces (and the antinode fetch)
   stay in sync through one path. */
( function () {
    function select( combo ) {
        document.querySelectorAll( '[data-combo]' ).forEach( function ( element ) {
            element.classList.toggle( 'sel', element.dataset.combo === combo );
        } );
    }
    document.querySelectorAll( '.ss-hm-cell' ).forEach( function ( cell ) {
        cell.addEventListener( 'click', function () { select( cell.dataset.combo ); } );
    } );
    document.querySelectorAll( '.rank-row' ).forEach( function ( row ) {
        row.addEventListener( 'click', function () {
            var cell = document.querySelector( '.ss-hm-cell[data-combo="' + row.dataset.combo + '"]' );
            if ( cell ) { cell.click(); }
        } );
    } );
} )();

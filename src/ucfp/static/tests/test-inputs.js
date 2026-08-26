/**
 * Unit tests for inputs.js -- the pure loan sink-selection logic (App.Inputs.selectLoanSink).
 *
 * selectLoanSink is the DOM-free core of solveLoan: given the writeable field classes (in knownness order,
 * least-known first), which are currently blank, and the class just edited, it returns the single field an
 * edit should (re-)derive. The fillers and the DOM reads around it are exercised manually.
 */
(function () {
    'use strict';

    // The four loan-field classes in the knownness order solveLoan passes (least-known first).
    var BALANCE = 'js-loan-balance';
    var TERM    = 'js-loan-term';
    var RATE    = 'js-loan-rate';
    var PAYMENT = 'js-loan-payment';
    var ALL     = [ BALANCE, TERM, RATE, PAYMENT ];   // the Profile surface: every field writeable
    var CARD    = [ TERM, RATE, PAYMENT ];            // the current-loan card: balance is read-only

    var sink = App.Inputs.selectLoanSink;

    QUnit.module( 'App.Inputs.selectLoanSink', function () {

        QUnit.test( 'fills the sole blank field (solve for the missing quantity)', function ( assert ) {
            assert.equal( sink( ALL, [ TERM ], PAYMENT ), TERM, 'blank term, editing payment -> fill term' );
            assert.equal( sink( ALL, [ RATE ], PAYMENT ), RATE, 'blank rate -> fill rate' );
            assert.equal( sink( ALL, [ PAYMENT ], RATE ), PAYMENT, 'blank payment -> fill payment' );
            assert.equal( sink( ALL, [ BALANCE ], RATE ), BALANCE, 'blank writeable balance -> fill balance' );
        } );

        QUnit.test( 'never refills the field being edited', function ( assert ) {
            assert.strictEqual( sink( ALL, [ TERM ], TERM ), null,
                'clearing the term (its own edit) does not immediately refill it' );
        } );

        QUnit.test( 'with none blank, re-derives the least-known writeable field that was not edited',
                    function ( assert ) {
            assert.equal( sink( ALL, [], PAYMENT ), BALANCE, 'Profile: edit payment -> balance (least known)' );
            assert.equal( sink( ALL, [], RATE ),    BALANCE, 'Profile: edit rate -> balance' );
            assert.equal( sink( ALL, [], TERM ),    BALANCE, 'Profile: edit term -> balance' );
            assert.equal( sink( ALL, [], BALANCE ), TERM,    'Profile: edit balance -> term (next least known)' );
        } );

        QUnit.test( 'adapts to the writeable set: the read-only-balance card sinks into the term',
                    function ( assert ) {
            assert.equal( sink( CARD, [], PAYMENT ), TERM, 'card: edit payment -> term (balance not writeable)' );
            assert.equal( sink( CARD, [], RATE ),    TERM, 'card: edit rate -> term' );
            assert.equal( sink( CARD, [], TERM ),    RATE, 'card: edit term -> rate' );
        } );

        QUnit.test( 'derives nothing when underdetermined (two or more blanks)', function ( assert ) {
            assert.strictEqual( sink( ALL, [ TERM, PAYMENT ], BALANCE ), null, 'two blanks -> null' );
            assert.strictEqual( sink( ALL, [ BALANCE, TERM, RATE ], PAYMENT ), null, 'three blanks -> null' );
        } );

        QUnit.test( 'a single-writeable surface with its one field edited derives nothing', function ( assert ) {
            assert.strictEqual( sink( [ PAYMENT ], [], PAYMENT ), null,
                'only payment writeable and it was the edit -> no other field to derive' );
        } );
    } );
})();

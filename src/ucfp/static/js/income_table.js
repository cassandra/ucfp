// §5 income table: client-side age<->date sync + background auto-save.
//
// The date is canonical; the age column beside it is a convenience kept in lockstep here so the
// server only ever reads dates (see ucfp/planning/income.py). Every edit auto-saves silently via
// antinode (loader suppressed, empty reply -> no DOM swap); the server re-renders the pane only on
// a structural change (a line added/removed) or a validation error. Handlers are delegated on
// `body` and scoped to `#income-table`, so they survive a pane swap and bind exactly once.

(function () {
  'use strict';

  function birthdateMap() {
    try { return JSON.parse($('#income-table').attr('data-birthdates') || '{}'); }
    catch (e) { return {}; }
  }

  // A date/age field's birthdate is either baked in (entitlement rows) or resolved live from the
  // row's currently chosen subject (general rows).
  function birthdateFor($field) {
    var fixed = $field.attr('data-birthdate');
    if (fixed) { return fixed; }
    var subjectId = $field.attr('data-subject-field');
    if (!subjectId) { return null; }
    return birthdateMap()[$('#' + subjectId).val()] || null;
  }

  // The birthday in (birth.year + age); 29 Feb in a non-leap target year falls back to the 28th,
  // matching the server's _at_age.
  function atAge(birthIso, age) {
    var parts = birthIso.split('-');
    var year = parseInt(parts[0], 10) + age, month = parts[1], day = parts[2];
    if (month === '02' && day === '29') { day = '28'; }
    return [year, month, day].join('-');
  }

  // Whole-year age a date falls on -- the inverse of atAge, matching the server's _derived_age.
  function ageOf(dateIso, birthIso) {
    return parseInt(dateIso.split('-')[0], 10) - parseInt(birthIso.split('-')[0], 10);
  }

  function fillDateFromAge($age) {
    var birth = birthdateFor($age);
    var age = parseInt($age.val(), 10);
    if (birth && !isNaN(age)) { $('#' + $age.attr('data-date-field')).val(atAge(birth, age)); }
  }

  function refreshAgeFromDate($date) {
    var birth = birthdateFor($date);
    var iso = $date.val();
    var $age = $('#' + $date.attr('data-age-field'));
    if (birth && /^\d{4}-\d{2}-\d{2}$/.test(iso)) { $age.val(ageOf(iso, birth)); }
    else if (!iso) { $age.val(''); }
  }

  function save($form) {
    AN.post($form.attr('action'), $form.serialize(), { suppressLoader: true });
  }

  $(function () {
    $('body').on('change', '#income-table input, #income-table select', function () {
      var $field = $(this);
      if ($field.hasClass('js-age')) { fillDateFromAge($field); }
      else if ($field.hasClass('js-date')) { refreshAgeFromDate($field); }
      save($field.closest('form'));
    });
    // Enter (or any submit) routes through the same silent save, never a full-page POST.
    $('body').on('submit', '#income-table form', function (event) {
      event.preventDefault();
      save($(this));
    });
  });
})();

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
    # HTML). BIRTHDATES holds a handle->ISO-date map on the table container;
    # the rest wire one date/age field to its partner and to a birthdate.
    BIRTHDATES_DATA_ATTR    = 'birthdates'
    BIRTHDATE_DATA_ATTR     = 'birthdate'
    SUBJECT_FIELD_DATA_ATTR = 'subject-field'
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

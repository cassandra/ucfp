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

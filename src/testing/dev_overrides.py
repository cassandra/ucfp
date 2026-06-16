class DevOverrideManager:
    """
    Home for DEBUG-only override hooks an app wires into its own code paths to
    exercise hard-to-reach states during development -- e.g. forcing form
    validation to fail so the error-display markup can be seen, or emitting
    trace output for a state machine.

    Unlike DevInjectionManager (which stores externally-injected payloads),
    these are in-process behaviors invoked directly from app code, always gated
    on ``settings.DEBUG``. Each hook is necessarily app-specific, so this class
    ships empty -- add classmethods here as the project needs them, for example:

        @classmethod
        def force_form_errors( cls, edit_form_data ):
            assert settings.DEBUG
            ...  # poke fake errors onto the bound forms, then return False
    """

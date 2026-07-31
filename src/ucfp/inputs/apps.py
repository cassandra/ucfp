from django.apps import AppConfig


class InputsConfig( AppConfig ):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ucfp.inputs'

    def ready( self ):
        from . import signals                               # noqa: F401 -- registers the post_delete receiver

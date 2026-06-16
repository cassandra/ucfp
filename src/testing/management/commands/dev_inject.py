import json

from django.core.management.base import BaseCommand, CommandError

from testing.dev_injection import DevInjectionManager


class Command( BaseCommand ):
    help = 'Inject named override data for development / UI testing (see DevInjectionManager).'

    def add_arguments( self, parser ):
        parser.add_argument( 'name', nargs = '?',
                             help = 'Name of the override to inject (read back under this name).' )
        parser.add_argument( 'data', nargs = '?',
                             help = 'JSON payload to inject.' )
        parser.add_argument( '--persistent', action = 'store_true',
                             help = 'Persist until cleared (default: consumed on first read).' )
        parser.add_argument( '--cache', action = 'store_true',
                             help = 'Store in the Django cache instead of a file.' )
        parser.add_argument( '--clear', action = 'store_true',
                             help = 'Clear all active overrides instead of injecting.' )
        parser.add_argument( '--list', action = 'store_true',
                             help = 'List all active overrides.' )

    def handle( self, *args, **options ):
        if options['list']:
            active = DevInjectionManager.list_active_overrides()
            if active:
                self.stdout.write( self.style.SUCCESS('Active overrides:') )
                for name, store in active.items():
                    self.stdout.write( f'  {name}: {store}' )
            else:
                self.stdout.write('No active overrides')
            return

        if options['clear']:
            if DevInjectionManager.clear_all_overrides():
                self.stdout.write( self.style.SUCCESS('Cleared all overrides') )
            else:
                self.stdout.write( self.style.ERROR('Failed to clear overrides (DEBUG not enabled?)') )
            return

        name = options['name']
        raw = options['data']
        if not name or raw is None:
            raise CommandError('Provide NAME and DATA to inject, or use --list / --clear.')

        try:
            payload = json.loads( raw )
        except json.JSONDecodeError as e:
            raise CommandError( f'Invalid JSON data: {e}' )

        one_time = not options['persistent']
        use_cache = options['cache']
        if DevInjectionManager.inject( name, payload, one_time = one_time, use_cache = use_cache ):
            storage = 'cache' if use_cache else 'file'
            persistence = 'one-time' if one_time else 'persistent'
            self.stdout.write( self.style.SUCCESS(
                f'Injected {name!r} ({persistence}, {storage})' ) )
        else:
            self.stdout.write( self.style.ERROR( 'Injection failed -- is DEBUG enabled?' ) )

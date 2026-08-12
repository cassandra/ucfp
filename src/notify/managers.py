from django.db import models


class UnsubscribedEmailModelManager( models.Manager ):

    def exists_by_user( self, user ):
        if not user.email:
            return False
        return self.exists_by_email( email = user.email )

    def exists_by_email( self, email : str ):
        if not email:
            return False
        return self.filter( email__iexact = email ).exists()

    def unsubscribe( self, email : str ):
        """Suppress all mail to this address. Idempotent."""
        if not email:
            return
        self.get_or_create( email = email )
        return

    def resubscribe( self, email : str ):
        """Re-enable mail to this address by removing any suppression. Idempotent
        -- the victim-controlled counterpart to unsubscribe."""
        if not email:
            return
        self.filter( email__iexact = email ).delete()
        return

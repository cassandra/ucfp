from django.urls import path


from . import views


urlpatterns = [

    path( 'account',
          views.UserAccountView.as_view(),
          name = 'user_account' ),

    path( 'attach-email',
          views.AttachEmailView.as_view(),
          name = 'attach_email' ),

    path( 'convert-to-guest',
          views.ConvertToGuestView.as_view(),
          name = 'convert_to_guest' ),

    path( 'signout',
          views.UserSignoutView.as_view(),
          name = 'user_signout' ),

    path( 'signin',
          views.UserSigninView.as_view(),
          name = 'user_signin' ),

    path( 'magic/code',
          views.MagicCodeView.as_view(),
          name = 'magic_code' ),

    path( 'magic/link/<uuid:user_uuid>/<str:token>',
          views.MagicLinkView.as_view(),
          name = 'magic_link' ),
]

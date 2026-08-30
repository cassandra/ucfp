from django.urls import path


from . import views


urlpatterns = [

    path( 'account',
          views.UserAccountView.as_view(),
          name = 'user_account' ),

    path( 'attach-email',
          views.AttachEmailView.as_view(),
          name = 'attach_email' ),

    path( 'signout',
          views.UserSignoutView.as_view(),
          name = 'user_signout' ),

    path( 'signin',
          views.UserSigninView.as_view(),
          name = 'user_signin' ),

    path( 'signin/existing',
          views.GuestSigninView.as_view(),
          name = 'guest_signin' ),

    path( 'magic/code',
          views.MagicCodeView.as_view(),
          name = 'magic_code' ),

    path( 'magic/link/<uuid:user_uuid>/<str:token>',
          views.MagicLinkView.as_view(),
          name = 'magic_link' ),
]

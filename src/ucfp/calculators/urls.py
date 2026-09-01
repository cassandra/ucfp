"""`/calculators/` -- the standalone calculators.

Each calculator is a self-contained feature package under this app, mounted here with its own nested
namespace, so their route names never collide. Public exposure is per-feature (a calculator is not public
just because it lives here): the Social Security timing calculator is login-free, exempted by its
namespace in the authentication middleware.
"""
from django.urls import include, path

app_name = 'calculators'

urlpatterns = [
    path( 'ss-timing/', include( 'ucfp.calculators.ss_timing.urls' ) ),
]

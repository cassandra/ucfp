"""The public home page surfaces the Social Security Timing calculator in a subordinate Calculators
section -- a no-signup on-ramp below the flagship Forecast/Explore pillars."""
from django.test import TestCase
from django.urls import reverse


class HomeCalculatorsSectionTest( TestCase ):

    def test_home_links_to_the_ss_timing_calculator( self ):
        response = self.client.get( reverse( 'home' ) )
        self.assertEqual( response.status_code, 200 )
        self.assertContains( response, 'Calculators' )
        self.assertContains( response, 'Social Security Timing' )
        self.assertContains( response, reverse( 'calculators:ss_timing:inputs' ) )

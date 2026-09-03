"""The methodology explanation for the results page: the SSA terms and their values for the selected
claiming strategy, shown in the "how this is calculated" modal.

US Social Security terminology (PIA, full retirement age, the claim reduction/credit, the spousal top-up,
the survivor benefit); the statutory values come from the jurisdiction facade, so the numbers here match
the ones the comparison ranks by.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ucfp.jurisdiction.enums import JurisdictionType
from ucfp.jurisdiction.government_pension import GovernmentPension

from .compute import member_claims

# The SSA research note that defines these terms (PIA, reduction/credit factors, spousal and survivor
# benefits) -- the reference the methodology modal links to.
REFERENCE_URL = 'https://www.ssa.gov/policy/docs/rsnotes/rsn2017-01.html'

# The SSA period life table behind the actuarial life-expectancy mode -- the mortality-basis citation the
# methodology modal links to when that mode is in use (see ucfp.jurisdiction.us.mortality).
LIFE_TABLE_URL = 'https://www.ssa.gov/oact/STATS/table4c6.html'

_GOVERNMENT_PENSION = GovernmentPension( JurisdictionType.US_FEDERAL )


@dataclass( frozen = True )
class Term:
    """One row of the methodology table: the SSA term, its short symbol, the value for this strategy, and a
    plain-language meaning."""

    label   : str
    symbol  : str
    value   : str
    meaning : str


def methodology( earners : tuple, claim_ages : tuple[ int, ... ] ) -> list[ Term ]:
    """The SSA terms behind the selected strategy: for each earner their PIA, full retirement age, claim
    age and its reduction/credit, and monthly benefit; plus -- for a couple -- the lower earner's spousal
    top-up and the household's survivor benefit. `earners` are higher earner first. A non-earning spouse has
    no own benefit, so their own terms are omitted; they claim their spousal top-up when the primary files
    (their resolved claiming date), which is what the spousal term below is reduced for."""
    claims      = member_claims( earners, claim_ages )
    own_claims  = [ claim for claim in claims if claim.is_earner ]
    couple      = len( earners ) == 2
    two_earners = len( own_claims ) == 2
    terms       = list()
    for index, claim in enumerate( own_claims ):
        earner  = claim.claimant
        suffix  = _suffix( two_earners, index )
        monthly = _own_monthly( earner, claim.claiming_date )
        terms += [
            Term( 'Primary Insurance Amount', f'PIA{suffix}', _money( earner.pia_monthly ),
                  'the benefit at full retirement age' ),
            Term( 'Full retirement age', f'FRA{suffix}', _age_label( earner.birthdate ),
                  'when the full PIA is payable' ),
            Term( 'Claim age', f'CA{suffix}', str( claim.claim_age ), 'the age this person files' ),
            Term( 'Reduction / credit', f'R{suffix}', _percent( monthly / earner.pia_monthly - 1 ),
                  'from claiming before or after full retirement age' ),
            Term( 'Monthly benefit', f'MB{suffix}', _money( monthly ),
                  'PIA times the claim adjustment' ) ]
    if couple:
        higher_claim, lower_claim = claims
        spousal = _spousal_monthly(
            higher_claim.claimant, lower_claim.claimant, lower_claim.claiming_date )
        if spousal > 0:
            terms.append( Term(
                'Spousal top-up', 'MB_s', _money( spousal ),
                'up to half the higher PIA, less the lower earner’s own benefit' ) )
        survivor = max( _own_monthly( higher_claim.claimant, higher_claim.claiming_date ),
                        _own_monthly( lower_claim.claimant, lower_claim.claiming_date ) )
        terms.append( Term(
            'Survivor benefit', 'MB_surv', _money( survivor ),
            'the larger benefit, paid to the survivor after the first death' ) )
    return terms


def _own_monthly( earner, claiming : date ) -> Decimal:
    return _GOVERNMENT_PENSION.realized_annual_benefit(
        earner.pia_monthly, earner.birthdate, claiming ) / 12


def _spousal_monthly( higher, lower, lower_claiming : date ) -> Decimal:
    return _GOVERNMENT_PENSION.spousal_excess_annual_benefit(
        higher.pia_monthly, lower.pia_monthly, lower.birthdate, lower_claiming ) / 12


def _age_label( birthdate : date ) -> str:
    """The full retirement age as a label -- '67', or '66 yr 2 mo' where it falls between birthdays."""
    years, months = divmod( _GOVERNMENT_PENSION.normal_retirement_age_months( birthdate ), 12 )
    return f'{years}' if months == 0 else f'{years} yr {months} mo'


def _suffix( two_earners : bool, index : int ) -> str:
    """The symbol suffix distinguishing two earners ('_h' / '_l'), empty when a single earner owns the only
    benefit block (a lone person, or a couple with a non-earning spouse)."""
    if not two_earners:
        return ''
    return '_h' if index == 0 else '_l'


def _money( amount : Decimal ) -> str:
    whole = amount.quantize( Decimal( '1' ), rounding = ROUND_HALF_UP )
    return '${:,}/mo'.format( whole )


def _percent( fraction : Decimal ) -> str:
    percent = ( fraction * Decimal( '100' ) ).quantize( Decimal( '0.1' ) )
    return f'{ "+" if percent > 0 else "" }{ percent }%'

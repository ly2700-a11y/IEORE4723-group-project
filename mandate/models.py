from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Rule(Strict):
    id: str = Field(min_length=1)
    kind: Literal['issuer_cap','sector_cap','cash_floor','prohibited_security','prohibited_type','min_rating','esg_exclusion','manual']
    description: str
    threshold: float | None = Field(default=None, ge=0, le=1)
    values: list[str] = Field(default_factory=list)
    rating: str | None = None
    basis: Literal['NAV','unsupported'] = 'NAV'
    timing: Literal['continuous','purchase_only','unsupported'] = 'continuous'
    evidence: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    evidence_verified: bool = True
    needs_review: bool = True
    approved: bool = False
    effective_from: date | None = None
    effective_to: date | None = None

    @model_validator(mode='after')
    def validate_parameters(self):
        if self.kind in ('issuer_cap','sector_cap','cash_floor') and self.threshold is None:
            raise ValueError('Percentage rule needs a fraction threshold, e.g. 0.10.')
        if self.kind in ('prohibited_security','prohibited_type') and not self.values:
            raise ValueError('Prohibition needs explicit values.')
        if self.kind == 'min_rating' and self.rating not in RATINGS:
            raise ValueError('Unsupported rating; use a manual rule.')
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValueError('Rule date range is reversed.')
        return self

RATINGS = ['AAA','AA+','AA','AA-','A+','A','A-','BBB+','BBB','BBB-','BB+','BB','BB-','B+','B','B-','CCC+','CCC','CCC-','CC','C','D']

class Rulebook(Strict):
    name: str
    source_sha256: str
    source_type: Literal['synthetic_ips','public_document','user_document']
    reviewed_by: str | None = None
    coverage_confirmed: bool = False
    rules: list[Rule] = Field(min_length=1)
    @model_validator(mode='after')
    def unique(self):
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError('Duplicate rule IDs.')
        return self

class Position(Strict):
    security_id: str = Field(min_length=1)
    market_value: float = Field(ge=0)

class Snapshot(Strict):
    as_of: date
    currency: Literal['USD'] = 'USD'
    cash: float = Field(ge=0)
    positions: list[Position]
    @model_validator(mode='after')
    def check(self):
        if len({p.security_id for p in self.positions}) != len(self.positions):
            raise ValueError('Duplicate security IDs; aggregate lots first.')
        if self.nav <= 0:
            raise ValueError('NAV must be positive.')
        return self
    @property
    def nav(self): return self.cash + sum(p.market_value for p in self.positions)

class Security(Strict):
    security_id: str
    issuer_id: str | None = None
    sector: str | None = None
    asset_type: str | None = None
    rating: str | None = None
    esg_excluded: bool | None = None
    as_of: date
    source: str = Field(min_length=1)

class Trade(Strict):
    trade_id: str
    security_id: str
    delta_value: float  # Positive buys, negative sells, in USD at the fixed snapshot valuation.
    fee: float = Field(default=0, ge=0)
    @model_validator(mode='after')
    def nonzero(self):
        if self.delta_value == 0: raise ValueError('Zero-value trade.')
        return self

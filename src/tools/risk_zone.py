"""
Risk zone validator: the deterministic check that runs beside the learned risk score, on the same gateway rows.

The transferred model (src/ml/transfer_scorer.py) rates how likely a charge is fraud, and only on Web and App charges.
This layer answers another question with no model and on every channel: was the charge made outside the customer's
home country? Zones are relative to the customer because the bank data holds a country and a city per charge and nothing
finer (28 cities, coordinates 81% null), and no label that could rank places (is_fraud carries no learnable signal,
TQ-023). The verdict is a fact for the human agent, in the audit log and the handoff packet: it never decides a turn and
never reaches the customer (TQ-038 asks the team what a charge in a risk zone should trigger).
"""
from __future__ import annotations

import html
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

ZONE_HOME = "HOME"  # the customer's city on file, or their country when a city is missing on either side
ZONE_DOMESTIC = "DOMESTIC_OTHER_CITY"
ZONE_ABROAD = "ABROAD"
ZONE_UNKNOWN = "UNKNOWN"  # no country on the charge or on the profile: nothing to validate
RISK_ZONES = frozenset({ZONE_ABROAD})
# address_distance_bucket of the feature contract, which the scorer computes with its own code (src/ml/bank_adapter.py)
ZONE_BUCKET = {ZONE_HOME: 0.0, ZONE_DOMESTIC: 1.0, ZONE_ABROAD: 2.0}


def _place(value: Any) -> str | None:
    """A country or city name to compare: unescaped (the gateways escape free text), without accents or case, so the
    dataset's "Mexico" and "México" are one country. A NaN, which pandas reads for a NULL, is no place."""
    if value is None or value != value:
        return None
    text = unicodedata.normalize("NFKD", html.unescape(str(value)))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip().casefold() or None


def _before(row: dict[str, Any], charge: dict[str, Any]) -> bool:
    """Whether the row is dated before the charge; a gateway returns every transaction_date in one format."""
    a, b = row.get("transaction_date"), charge.get("transaction_date")
    return a is not None and b is not None and str(a) < str(b)


def cross_check(in_risk_zone: bool, model_flags: bool) -> str:
    """Which of the two checks flags the charge: BOTH, MODEL_ONLY, ZONE_ONLY or NEITHER."""
    if model_flags:
        return "BOTH" if in_risk_zone else "MODEL_ONLY"
    return "ZONE_ONLY" if in_risk_zone else "NEITHER"


@dataclass(frozen=True)
class RiskZoneVerdict:
    zone: str
    in_risk_zone: bool
    charge_country: str | None
    charge_city: str | None
    home_country: str | None
    home_city: str | None
    earlier_charges_read: int = 0  # the customer's charges before this one among the rows the gateway returned
    earlier_charges_in_place: int = 0  # of those, the ones made in the charge's country (abroad) or city (another city)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fact(self) -> str:
        """One line for the handoff's verified facts (English, as the console)."""
        if self.zone == ZONE_UNKNOWN:
            return "Risk zone check: not validated, the charge or the customer profile has no country on record"
        where = ", ".join(str(p) for p in (self.charge_city, self.charge_country) if p)
        verdict = "in a risk zone" if self.in_risk_zone else "not in a risk zone"
        if self.zone == ZONE_HOME:
            return f"Risk zone check: charge made in {where}, the customer's home {'city' if self.charge_city and self.home_city else 'country'}: {verdict}"
        place, relation = ((self.charge_country, f"outside the customer's home country ({self.home_country})") if self.zone == ZONE_ABROAD
                           else (self.charge_city, f"in the customer's home country but not their city on file ({self.home_city})"))
        history = (f"{self.earlier_charges_in_place} of the customer's {self.earlier_charges_read} earlier charges read were made in {place}"
                   if self.earlier_charges_read else "no earlier charge of the customer was read")
        return f"Risk zone check: charge made in {where}, {relation}: {verdict}; {history}"


class RiskZoneValidator:
    """Takes what the risk scorer takes, (matched, history, profile), and shares no code with it: two readings of one charge."""

    def __call__(self, matched: dict[str, Any], history: list[dict[str, Any]], profile: dict[str, Any]) -> RiskZoneVerdict:
        country, city = matched.get("transaction_country"), matched.get("transaction_city")
        home_country, home_city = profile.get("country"), profile.get("city")
        zone = self._zone(country, city, home_country, home_city)
        earlier = [r for r in history if r.get("transaction_id") != matched.get("transaction_id") and _before(r, matched)]
        in_place = 0
        if zone in (ZONE_ABROAD, ZONE_DOMESTIC):
            key = "transaction_country" if zone == ZONE_ABROAD else "transaction_city"
            in_place = sum(1 for r in earlier if _place(r.get(key)) == _place(matched.get(key)))
        return RiskZoneVerdict(zone=zone, in_risk_zone=zone in RISK_ZONES, charge_country=country, charge_city=city,
                               home_country=home_country, home_city=home_city, earlier_charges_read=len(earlier),
                               earlier_charges_in_place=in_place)

    @staticmethod
    def _zone(country: Any, city: Any, home_country: Any, home_city: Any) -> str:
        charge, home = _place(country), _place(home_country)
        if charge is None or home is None:
            return ZONE_UNKNOWN
        if charge != home:
            return ZONE_ABROAD
        charge_city, own_city = _place(city), _place(home_city)
        return ZONE_DOMESTIC if (charge_city is not None and own_city is not None and charge_city != own_city) else ZONE_HOME

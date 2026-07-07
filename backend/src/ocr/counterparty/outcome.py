"""VerificationOutcome (PAT-1 / ADR-0011): contrato del que cuelga la pantalla
de revisión. Enriquece CheckResult (que NO se toca) con fuente/nivel/bloqueo."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CifStatus(StrEnum):
    valid = "valid"
    invalid = "invalid"
    not_found = "not_found"
    unverified = "unverified"


class NameMatch(StrEnum):
    match = "match"
    mismatch = "mismatch"
    unknown = "unknown"


@dataclass(frozen=True)
class VerificationOutcome:
    status: CifStatus
    name_match: NameMatch
    source: str                # 'structure' | 'supplier_master' | 'cache:*' | 'vies' | 'aeat' | …
    blocking: bool             # True ⇒ deshabilita "Confirmar y guardar" (§3.6 regla 12)
    official_name: str | None
    reason: str                # mensaje en español para la UI y el audit_log

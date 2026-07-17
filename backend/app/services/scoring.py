"""Deterministic Stage 3 scoring engine — no LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Campaign, Company, CompanySourceRecord
from app.models.enums import QualificationStatus, SCORING_VERSION
from app.services.normalize import normalize_company_name, normalize_domain_for_match, normalize_location

# stage3-v1 rubric (max positive = 100 before clamp; penalties reduce):
#   DOMAIN_PRESENT           +20
#   INDUSTRY_MATCH           +25  (or PARTIAL +12)
#   LOCATION_MATCH           +20
#   PROFILE_COMPLETENESS     +15  (website 5 + description 5 + locations 5)
#   PROVENANCE_CONFIRMED     +10
#   MULTI_SOURCE             +10  (unique data_source_id + external_id >= 2)
# Penalties:
#   DOMAIN_SUSPICIOUS        -10
#   DOMAIN_CONFLICT          -20
#   NAME_MISSING             -25
#   PROVENANCE_MISSING       -15
# Final score = clamp(total, 0, 100)


@dataclass(frozen=True)
class ScoreReason:
    code: str
    points: int
    detail: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "points": self.points, "detail": self.detail}


@dataclass
class ScoreResult:
    score: int
    qualification_status: QualificationStatus
    reasons: list[ScoreReason] = field(default_factory=list)
    scoring_version: str = SCORING_VERSION
    input_snapshot: dict = field(default_factory=dict)


def classify_score(score: int) -> QualificationStatus:
    if score >= 70:
        return QualificationStatus.QUALIFIED
    if score >= 40:
        return QualificationStatus.REVIEW
    return QualificationStatus.DISQUALIFIED


def _token_set(value: str | None) -> set[str]:
    """Whitespace-token set after normalization — not substring matching."""
    if not value:
        return set()
    normalized = normalize_company_name(value) or normalize_location(value)
    if not normalized:
        return set()
    return {t for t in normalized.split() if t}


def _token_overlap(a: str | None, b: str | None) -> float:
    ta = _token_set(a)
    tb = _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _location_tokens(company: Company) -> set[str]:
    tokens: set[str] = set()
    locations = sorted(
        company.locations or [],
        key=lambda loc: (loc.country or "", loc.region or "", loc.city or "", str(loc.id)),
    )
    for loc in locations:
        for raw in (loc.region, loc.city, loc.country):
            tokens |= _token_set(raw)
    return tokens


def _is_valid_domain(domain: str | None) -> bool:
    if not domain:
        return False
    # Require a dot TLD-like shape; reject leading dots / spaces.
    if " " in domain or domain.startswith(".") or domain.endswith("."):
        return False
    if "." not in domain:
        return False
    labels = domain.split(".")
    return all(label and label.replace("-", "").isalnum() for label in labels)


def _unique_source_keys(provenance_records: list[CompanySourceRecord]) -> list[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for rec in sorted(
        provenance_records,
        key=lambda r: (str(r.data_source_id), r.external_id or "", str(r.id)),
    ):
        key = (str(rec.data_source_id), rec.external_id or str(rec.id))
        if key not in keys:
            keys.add(key)
            ordered.append(key)
    return ordered


def score_company(
    *,
    campaign: Campaign,
    company: Company,
    provenance_records: list[CompanySourceRecord],
    has_domain_conflict: bool = False,
) -> ScoreResult:
    """stage3-v1 rubric. Same logical inputs → same score (order-independent)."""
    reasons: list[ScoreReason] = []
    total = 0

    domain = normalize_domain_for_match(company.domain)
    name_ok = bool(normalize_company_name(company.name))

    if _is_valid_domain(domain):
        total += 20
        reasons.append(ScoreReason("DOMAIN_PRESENT", 20, domain or ""))
    elif domain:
        total -= 10
        reasons.append(ScoreReason("DOMAIN_SUSPICIOUS", -10, domain))
    else:
        reasons.append(ScoreReason("DOMAIN_MISSING", 0, "no domain"))

    industry_parts = [
        company.description or "",
        company.name or "",
        company.legal_name or "",
    ]
    industry_hay = " ".join(p for p in industry_parts if p)
    overlap = _token_overlap(campaign.business_type, industry_hay)
    overlap_s = f"{overlap:.2f}"
    if overlap >= 0.5:
        total += 25
        reasons.append(ScoreReason("INDUSTRY_MATCH", 25, f"overlap={overlap_s}"))
    elif overlap >= 0.2:
        total += 12
        reasons.append(ScoreReason("INDUSTRY_PARTIAL", 12, f"overlap={overlap_s}"))
    else:
        reasons.append(ScoreReason("INDUSTRY_MISMATCH", 0, f"overlap={overlap_s}"))

    camp_loc = normalize_location(campaign.region) or ""
    loc_tokens = _location_tokens(company)
    camp_tokens = _token_set(camp_loc)
    if camp_tokens and loc_tokens and camp_tokens & loc_tokens:
        total += 20
        reasons.append(ScoreReason("LOCATION_MATCH", 20, camp_loc))
    elif camp_tokens and not loc_tokens:
        reasons.append(ScoreReason("LOCATION_UNKNOWN", 0, "company has no location"))
    else:
        reasons.append(ScoreReason("LOCATION_MISMATCH", 0, camp_loc))

    completeness = 0
    if company.website:
        completeness += 5
    if company.description and len(company.description.strip()) >= 10:
        completeness += 5
    if company.locations:
        completeness += 5
    total += completeness
    reasons.append(ScoreReason("PROFILE_COMPLETENESS", completeness, f"{completeness}/15"))

    unique_sources = _unique_source_keys(provenance_records)
    if unique_sources:
        total += 10
        reasons.append(
            ScoreReason("PROVENANCE_CONFIRMED", 10, f"n={len(unique_sources)}")
        )
        if len(unique_sources) >= 2:
            total += 10
            reasons.append(ScoreReason("MULTI_SOURCE", 10, f"sources={len(unique_sources)}"))
        else:
            reasons.append(ScoreReason("SINGLE_SOURCE", 0, "one source"))
    else:
        total -= 15
        reasons.append(ScoreReason("PROVENANCE_MISSING", -15, "no source records"))

    if has_domain_conflict:
        total -= 20
        reasons.append(ScoreReason("DOMAIN_CONFLICT", -20, "conflicting domain/source"))
    if not name_ok:
        total -= 25
        reasons.append(ScoreReason("NAME_MISSING", -25, "empty name"))

    score = max(0, min(100, total))
    status = classify_score(score)

    input_snapshot = {
        "scoring_version": SCORING_VERSION,
        "campaign": {
            "id": str(campaign.id),
            "business_type": campaign.business_type,
            "region": campaign.region,
        },
        "company": {
            "id": str(company.id),
            "name": company.name,
            "domain": domain,
            "website": company.website,
            "has_description": bool(company.description),
            "location_count": len(company.locations or []),
        },
        "provenance_count": len(unique_sources),
        "provenance_keys": [f"{a}:{b}" for a, b in unique_sources],
        "has_domain_conflict": has_domain_conflict,
    }

    return ScoreResult(
        score=score,
        qualification_status=status,
        reasons=reasons,
        scoring_version=SCORING_VERSION,
        input_snapshot=input_snapshot,
    )

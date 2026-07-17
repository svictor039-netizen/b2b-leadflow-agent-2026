"""Company merge and deduplication for Stage 2 research."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanySourceRecord, DataSource, ResearchItemOutcome
from app.providers.base import CompanyRecord
from app.services.normalize import (
    normalize_company_name,
    normalize_domain_for_match,
    normalize_source_id,
)


@dataclass
class DedupMatch:
    company: Company | None
    outcome_hint: ResearchItemOutcome
    reason: str


def find_by_source_external(
    db: Session,
    data_source_id: UUID,
    external_id: str | None,
) -> CompanySourceRecord | None:
    external_id = normalize_source_id(external_id)
    if not external_id:
        return None
    return db.scalar(
        select(CompanySourceRecord).where(
            CompanySourceRecord.data_source_id == data_source_id,
            CompanySourceRecord.external_id == external_id,
        )
    )


def find_by_domain(db: Session, domain: str | None) -> Company | None:
    domain = normalize_domain_for_match(domain)
    if not domain:
        return None
    # Domains are stored normalized — exact match uses unique index.
    exact = db.scalar(select(Company).where(Company.domain == domain))
    if exact is not None:
        return exact
    companies = db.scalars(select(Company).where(Company.domain.is_not(None))).all()
    for company in companies:
        if normalize_domain_for_match(company.domain) == domain:
            return company
    return None


def find_by_name_location_fallback(
    db: Session,
    name: str,
    location: str | None,
) -> Company | None:
    """Fallback only when domain is absent — exact normalized name + location."""
    norm_name = normalize_company_name(name)
    if not norm_name:
        return None
    from app.services.normalize import normalize_location

    norm_loc = normalize_location(location)
    candidates = db.scalars(select(Company)).all()
    matches: list[Company] = []
    for company in candidates:
        if normalize_company_name(company.name) != norm_name:
            continue
        if company.domain:
            # Prefer not to name-match when company already has a domain identity
            continue
        if norm_loc:
            # Without locations loaded, compare description/region loosely via locations
            locs = company.locations or []
            loc_ok = any(
                normalize_location(loc.city) == norm_loc
                or normalize_location(loc.region) == norm_loc
                or normalize_location(loc.country) == norm_loc
                for loc in locs
            )
            if not loc_ok and locs:
                continue
        matches.append(company)
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_match(
    db: Session,
    record: CompanyRecord,
    data_source: DataSource,
) -> DedupMatch:
    incoming_domain = normalize_domain_for_match(record.domain)

    source_hit = find_by_source_external(db, data_source.id, record.source_record_id)
    if source_hit is not None:
        company = db.get(Company, source_hit.company_id)
        if company is None:
            return DedupMatch(None, ResearchItemOutcome.CREATED, "source_record_orphan")
        existing_domain = normalize_domain_for_match(company.domain)
        if (
            incoming_domain
            and existing_domain
            and incoming_domain != existing_domain
        ):
            return DedupMatch(
                company,
                ResearchItemOutcome.CONFLICT,
                "source_id_domain_mismatch",
            )
        return DedupMatch(company, ResearchItemOutcome.MATCHED_EXISTING, "source_external_id")

    if incoming_domain:
        by_domain = find_by_domain(db, incoming_domain)
        if by_domain is not None:
            return DedupMatch(by_domain, ResearchItemOutcome.MATCHED_EXISTING, "domain")
        return DedupMatch(None, ResearchItemOutcome.CREATED, "new_domain")

    # No domain — fallback name+location only
    fallback = find_by_name_location_fallback(db, record.name, record.region)
    if fallback is not None:
        return DedupMatch(fallback, ResearchItemOutcome.MATCHED_EXISTING, "name_location")
    return DedupMatch(None, ResearchItemOutcome.CREATED, "new_no_domain")


def merge_company_fields(company: Company, record: CompanyRecord) -> bool:
    """Fill empty fields only. Never overwrites display name or non-empty values."""
    changed = False

    def fill(attr: str, new_value: str | None) -> None:
        nonlocal changed
        if not new_value:
            return
        current = getattr(company, attr)
        if current is None or (isinstance(current, str) and not current.strip()):
            setattr(company, attr, new_value)
            changed = True

    # Do not change company.name — display name stays as first-seen value.
    fill("description", record.description or None)
    if not company.website and record.website:
        company.website = record.website.strip()
        changed = True
    if not company.domain and record.domain:
        company.domain = normalize_domain_for_match(record.domain)
        changed = True
    return changed

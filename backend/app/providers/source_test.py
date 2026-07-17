from app.providers.base import CompanyRecord, SourceAdapter

_DEMO_COMPANIES: list[CompanyRecord] = [
    CompanyRecord(
        name="Nordic SaaS Labs",
        domain="nordicsaas.example",
        region="Northern Europe",
        niche="B2B SaaS",
        contact_email="hello@nordicsaas.example",
        description="Demo SaaS company for stage 0 testing.",
    ),
    CompanyRecord(
        name="Baltic Logistics Pro",
        domain="balticlog.example",
        region="Baltic States",
        niche="Logistics",
        contact_email="sales@balticlog.example",
        description="Demo logistics company.",
    ),
    CompanyRecord(
        name="Central FinTech Group",
        domain="centralfin.example",
        region="Central Europe",
        niche="FinTech",
        contact_email="info@centralfin.example",
        description="Demo FinTech company.",
    ),
    CompanyRecord(
        name="Green Energy Partners",
        domain="greenenergy.example",
        region="DACH",
        niche="Renewable Energy",
        contact_email="contact@greenenergy.example",
        description="Demo energy sector company.",
    ),
    CompanyRecord(
        name="MedTech Innovations",
        domain="medtech.example",
        region="Western Europe",
        niche="Healthcare IT",
        contact_email="team@medtech.example",
        description="Demo healthcare IT company.",
    ),
]


class TestSourceAdapter(SourceAdapter):
    """Returns fixed demo companies — no real catalog or scraping."""

    @property
    def name(self) -> str:
        return "test_source"

    def search(self, niche: str, region: str, limit: int = 30) -> list[CompanyRecord]:
        effective_limit = min(limit, 30)
        results: list[CompanyRecord] = []
        for company in _DEMO_COMPANIES:
            if len(results) >= effective_limit:
                break
            if niche.lower() in company.niche.lower() or region.lower() in company.region.lower():
                results.append(company)
        if not results:
            results = _DEMO_COMPANIES[: min(effective_limit, len(_DEMO_COMPANIES))]
        return results

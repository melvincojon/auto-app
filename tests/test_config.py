from job_monitor.adapters import supported_adapters
from job_monitor.config import load_companies


def test_every_production_company_has_supported_adapter():
    companies = load_companies("companies.yaml")
    assert len(companies) == 16
    assert {company.adapter for company in companies} <= supported_adapters()

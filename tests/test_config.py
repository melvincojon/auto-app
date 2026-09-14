from job_monitor.adapters import supported_adapters
from job_monitor.config import load_companies


def test_every_production_company_has_supported_adapter():
    companies = load_companies("companies.yaml")
    assert len(companies) == 16
    assert {company.adapter for company in companies} <= supported_adapters()


def test_split_discovery_configuration_is_scoped_to_eightfold():
    companies = load_companies("companies.yaml")
    by_name = {company.company: company for company in companies}
    configured = {
        company.company
        for company in companies
        if company.get("discovery_pages") is not None
    }
    assert configured == {"Microsoft", "Netflix"}
    assert by_name["Microsoft"].get("discovery_pages") == 2
    assert by_name["Microsoft"].get("params")["sort_by"] == "timestamp"
    assert by_name["Netflix"].get("discovery_pages") == 5

from __future__ import annotations

import pytest

from job_monitor.classifier import classify
from job_monitor.models import Job, MatchCategory


def job(
    title: str,
    description: str = "",
    location: str | None = "New York, NY",
    *,
    company: str = "Acme",
) -> Job:
    return Job(company, "test", "1", title, description, location, None, "https://x/1")


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Software Engineer, University Graduate", "Start in 2027"),
        ("Backend Engineer", "This entry-level role requires 0-2 years."),
        ("Flight Software Engineer", "Open to recent graduates."),
        ("Member of Technical Staff", "This is a campus hiring opportunity."),
        ("Quantitative Developer", "2027 graduate program"),
        ("SDE I", "Build reliable systems"),
        ("Associate Engineer", "Software engineering team"),
        ("Software Engineer - I", "Build APIs"),
        ("Software Engineer", "Must graduate between December 2026 and August 2027"),
        ("Software Engineer - New Grad", "Eligible graduation: Fall 2026 or Spring 2027"),
        ("Software Engineer", "0-1 years of professional software development"),
        ("Software Engineer", "0–2 years professional software development"),
        ("Software Engineer", "0 to 2 years of engineering experience"),
        ("Software Engineer", "Up to 2 years of professional software development"),
        ("Graduate Software Engineer", "Currently in your final year of study or equivalent"),
        ("Graduate Software Engineer", "Expected graduation by Summer 2027"),
        ("Software Engineer", "Graduating May 2027 or June 2027"),
        ("Software Engineer", "Degree earned within the last year"),
    ],
)
def test_explicit_early_career_matches(title, description):
    result = classify(job(title, description))
    assert result is not None
    assert result.category == MatchCategory.NEW_GRAD_MATCH


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer",
        "Infrastructure Engineer",
        "Platform Engineer",
        "Site Reliability Engineer",
        "Forward Deployed AI Engineer",
        "Applied Research Engineer",
        "ML Engineer",
        "Quantitative Technologist",
    ],
)
def test_ambiguous_relevant_roles_notify(title):
    result = classify(job(title, "Build important production systems."))
    assert result is not None
    assert result.category == MatchCategory.POSSIBLE_NEW_GRAD_MATCH


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Senior Software Engineer", "New graduate program mentor"),
        ("Staff Backend Engineer", "Build APIs"),
        ("Software Engineer III", "Build APIs"),
        ("Software Engineer - II - Windows Systems", "Build operating systems"),
        ("Software Engineer Intern", "New graduate friendly"),
        ("Software Engineering Co-op", "Entry level"),
        ("Software Engineer", "This is a paid summer internship."),
        ("Account Executive", "Work alongside software engineers"),
        ("Digital Solution Engineering (Cloud & AI Data)", "Build software"),
        ("Hardware Engineer", "Develop embedded software"),
        ("Electrical Engineer", "Work with software teams"),
        ("Mechanical Engineer", "Write Python tools"),
        ("Silicon Engineer", "Entry-level software development"),
        ("Solution Consultant", "Technical pre-sales with software customers"),
    ],
)
def test_title_exclusions(title, description):
    assert classify(job(title, description)) is None


@pytest.mark.parametrize(
    "description",
    [
        "2+ years software engineering experience required",
        "3+ years of software engineering preferred",
        "3+ years non-internship professional software development experience",
        "Minimum 2 years of professional experience",
        "Minimum of 2+ years relevant engineering experience",
        "Minimum of 2+ years of non-internship professional software development",
        "At least 2+ years of software development experience",
        "4+ years technical pre-sales experience",
        "5+ years relevant industry experience",
        "Minimum 5 years of experience required.",
    ],
)
def test_affirmative_experience_requirements_are_excluded(description):
    assert classify(job("Software Engineer", description)) is None


@pytest.mark.parametrize(
    "description",
    [
        "2+ years using Python and Linux is helpful.",
        "At least 2 years using Python or Linux is helpful.",
        "Our team has 10+ years of software engineering experience.",
        "Work with senior engineers with 5+ years of professional experience.",
        "Higher-level roles may require 5+ years of software engineering experience.",
        "Candidates range from new graduates to senior engineers.",
        "You will receive senior mentorship and collaborate across teams.",
    ],
)
def test_incidental_experience_and_senior_language_do_not_exclude(description):
    result = classify(job("Software Engineer - New Grad", f"0-2 years. {description}"))
    assert result is not None
    assert result.category == MatchCategory.NEW_GRAD_MATCH


def test_team_boilerplate_does_not_mask_a_separate_candidate_requirement():
    description = (
        "Our team has 10+ years of software engineering experience. "
        "Candidates need 3+ years of professional software development experience."
    )
    assert classify(job("Software Engineer", description)) is None


@pytest.mark.parametrize(
    "location",
    [
        "New York, NY",
        "New York NY",
        "Seattle, WA",
        "San Francisco, CA",
        "US, CA, San Francisco",
        "United States",
        "USA",
        "Remote - US",
        "Remote - United States",
        "Toronto, Canada; New York, NY",
        "London; Seattle, WA",
        "Toronto, Canada; Seattle, Washington",
        "Indianapolis, IN",
    ],
)
def test_us_locations_are_eligible(location):
    result = classify(job("Software Engineer", location=location))
    assert result is not None
    assert result.category == MatchCategory.POSSIBLE_NEW_GRAD_MATCH


@pytest.mark.parametrize(
    "location",
    [
        "Remote",
        "Multiple Locations",
        "NYC",
        None,
        "",
    ],
)
def test_ambiguous_or_missing_locations_are_eligible(location):
    assert classify(job("Software Engineer", location=location)) is not None


@pytest.mark.parametrize(
    "location",
    [
        "Remote - Canada",
        "Toronto, Canada",
        "Vancouver, Canada",
        "IN, KA, Bengaluru",
        "Bengaluru, IN",
        "TS, Hyderabad",
        "Bengaluru, India",
        "Tel Aviv, Israel",
        "London, UK",
    ],
)
def test_foreign_only_locations_are_excluded(location):
    assert classify(job("Software Engineer", location=location)) is None


def test_bachelors_degree_alone_is_not_an_early_career_signal():
    result = classify(
        job("Software Engineer", "Bachelor's degree in Computer Science required")
    )
    assert result is not None
    assert result.category == MatchCategory.POSSIBLE_NEW_GRAD_MATCH


def test_bare_2027_is_not_an_early_career_signal():
    result = classify(job("Software Engineer", "The product roadmap extends through 2027."))
    assert result is not None
    assert result.category == MatchCategory.POSSIBLE_NEW_GRAD_MATCH


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Member of Technical Staff", MatchCategory.POSSIBLE_NEW_GRAD_MATCH),
        ("Member of Technical Staff I", MatchCategory.POSSIBLE_NEW_GRAD_MATCH),
        ("Senior Member of Technical Staff", None),
        ("Sr. Member of Technical Staff", None),
        ("Principal Member of Technical Staff", None),
        ("Lead Member of Technical Staff", None),
        ("Manager, Member of Technical Staff", None),
    ],
)
def test_member_of_technical_staff_seniority(title, expected):
    result = classify(job(title))
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result.category == expected


@pytest.mark.parametrize(
    "title",
    [
        "Software Development Engineer I - Early Career (2027 Starts)",
        "Software Development Engineer (2027 Starts)",
    ],
)
def test_2027_starts_is_an_early_career_signal(title):
    result = classify(job(title))
    assert result is not None
    assert result.category == MatchCategory.NEW_GRAD_MATCH


@pytest.mark.parametrize(
    "description",
    [
        "2 years of software engineering experience required",
        "2 years of professional software development experience",
        "2 years professional software engineering experience required",
        "3 years of relevant industry experience",
        "4 years of professional engineering experience preferred",
    ],
)
def test_plain_affirmative_experience_requirements_are_excluded(description):
    assert classify(job("Software Engineer", description)) is None


@pytest.mark.parametrize(
    "description",
    [
        "0-2 years of professional software development experience",
        "0 to 2 years of professional engineering experience",
        "Up to 2 years of software engineering experience",
        "2+ years using Python",
        "2+ years working with Linux",
        "Work with engineers who have 10+ years of professional experience",
    ],
)
def test_plain_experience_requirement_protected_cases(description):
    result = classify(job("Software Engineer - New Grad", description))
    assert result is not None
    assert result.category == MatchCategory.NEW_GRAD_MATCH


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer, Hardware Infrastructure",
        "Software Engineer, Silicon Systems",
        "Software Engineer - Hardware Platform",
        "Embedded Software Engineer, Hardware Systems",
    ],
)
def test_software_roles_with_hardware_domain_descriptors_are_eligible(title):
    assert classify(job(title)) is not None


@pytest.mark.parametrize(
    "title",
    [
        "Hardware Systems Engineer",
        "Silicon Validation Engineer",
    ],
)
def test_additional_clearly_nonsoftware_roles_are_excluded(title):
    assert classify(job(title)) is None


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("2027 Graduate Program", "Join as a software developer working on production systems."),
        ("Technology Graduate Program", "You will join the firm as a quantitative developer."),
    ],
)
def test_graduate_program_role_fallback(title, description):
    result = classify(job(title, description))
    assert result is not None
    assert result.category == MatchCategory.NEW_GRAD_MATCH


def test_unrelated_title_does_not_use_description_role_fallback():
    assert classify(job("Account Executive", "Work closely with software developers")) is None


@pytest.mark.parametrize(
    ("company", "title", "description", "location", "expected"),
    [
        ("Coinbase", "Software Engineer- Money Movement", "Build payments", "Remote - Canada", None),
        ("Amazon", "Software Development Engineer, Amazon", "Bachelor's degree required", "IN, KA, Bengaluru", None),
        ("Amazon", "Software Engineer, XR, Fauna", "3+ years non-internship professional software development", "US", None),
        ("Amazon", "Software Development Engineer, MediaTailor", "3+ years non-internship professional software development", "United States", None),
        ("Ramp", "Software Engineer, Forward Deployed", "3+ years software engineering preferred", "New York, NY", None),
        ("Acme", "Software Engineer", "Bachelor's degree in Computer Science required", "New York, NY", MatchCategory.POSSIBLE_NEW_GRAD_MATCH),
        ("Acme", "Software Engineer - New Grad", "Fall 2026 or Spring 2027 graduation", "San Francisco, CA", MatchCategory.NEW_GRAD_MATCH),
        ("Acme", "Software Engineer", "0-2 years professional software development", "Los Angeles, CA", MatchCategory.NEW_GRAD_MATCH),
        ("Acme", "Graduate Software Engineer", "Final year of study or equivalent", "Chicago, IL", MatchCategory.NEW_GRAD_MATCH),
        ("Acme", "Graduate Software Engineer", "Expected graduation by Summer 2027", "New York, NY", MatchCategory.NEW_GRAD_MATCH),
        ("Acme", "Software Engineer", "Build APIs", "Toronto, Canada; Seattle, WA", MatchCategory.POSSIBLE_NEW_GRAD_MATCH),
        ("Acme", "Software Engineer", "Build APIs", "Remote", MatchCategory.POSSIBLE_NEW_GRAD_MATCH),
    ],
)
def test_requested_regressions(company, title, description, location, expected):
    result = classify(job(title, description, location, company=company))
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result.category == expected

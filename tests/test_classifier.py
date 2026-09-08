from __future__ import annotations

import pytest

from job_monitor.classifier import classify
from job_monitor.models import Job, MatchCategory


def job(title: str, description: str = "") -> Job:
    return Job("Acme", "test", "1", title, description, "NYC", None, "https://x/1")


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Software Engineer, University Graduate", "Start in 2027"),
        ("Backend Engineer", "This entry-level role requires 0-2 years."),
        ("Flight Software Engineer", "Open to recent graduates."),
        ("Member of Technical Staff", "Campus opportunity for bachelor's graduates."),
        ("Quantitative Developer", "2027 graduate program"),
        ("SDE I", "Build reliable systems"),
        ("Associate Engineer", "Software engineering team"),
        ("Software Engineer", "Bachelor's degree in computer science"),
        ("Software Engineer - I", "Build APIs"),
        ("Software Engineer", "Must graduate between December 2026 and August 2027"),
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
        "Forward Deployed AI Engineer",
        "Applied Research Engineer",
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
        ("Software Engineer", "Minimum 5 years of experience required."),
        ("Software Engineer Intern", "New graduate friendly"),
        ("Software Engineering Co-op", "Entry level"),
        ("Software Engineer", "This is a paid summer internship."),
        ("Account Executive", "Work alongside software engineers"),
    ],
)
def test_exclusions(title, description):
    assert classify(job(title, description)) is None


def test_description_can_supply_technical_and_early_career_signals():
    result = classify(job("2027 Graduate Program", "Join as a software developer."))
    assert result is not None
    assert result.category == MatchCategory.NEW_GRAD_MATCH

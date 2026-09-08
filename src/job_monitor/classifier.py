from __future__ import annotations

import re

from .models import Job, Match, MatchCategory


_TECHNICAL = re.compile(
    r"\b(?:"
    r"software\s+(?:development\s+)?engineer|software\s+developer|"
    r"software\s+engineering\s+associate|software\s+engineer|"
    r"sde(?:\s+i)?|backend\s+engineer|back-end\s+engineer|"
    r"infrastructure\s+engineer|platform\s+engineer|systems?\s+engineer|"
    r"site\s+reliability\s+engineer|devops\s+engineer|"
    r"full[ -]?stack\s+(?:engineer|developer)|flight\s+software\s+engineer|"
    r"forward\s+deployed(?:\s+ai)?\s+engineer|applied\s+research\s+engineer|"
    r"machine\s+learning\s+engineer|ai\s+engineer|"
    r"member\s+of\s+technical\s+staff|associate\s+(?:software\s+)?engineer|"
    r"junior\s+(?:software\s+)?engineer|quantitative\s+developer|"
    r"quant\s+developer|quantitative\s+technologist"
    r")\b",
    re.I,
)

_INTERNSHIP_TITLE = re.compile(r"\b(?:intern(?:ship)?|co[ -]?op)\b", re.I)
_INTERNSHIP_DESCRIPTION = re.compile(
    r"\b(?:this|our|paid|summer|winter|spring|fall)\s+(?:software\s+engineering\s+)?intern(?:ship)?\b|"
    r"\b(?:is|work)\s+as\s+(?:a\s+)?(?:\d+[- ]week\s+)?intern(?:ship)?\b|"
    r"\bemployment\s+type\s*:?\s*intern(?:ship)?\b",
    re.I,
)

_SENIOR_TITLE = re.compile(
    r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|head\s+of|"
    r"engineer\s*(?:[-–—]\s*)?(?:ii|iii|iv|2|3|4)|"
    r"sde\s*(?:[-–—]\s*)?(?:ii|iii|iv|2|3|4)"
    r")\b",
    re.I,
)

_EARLY_SIGNALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bnew\s+(?:college\s+)?grad(?:uate)?s?\b", re.I), "new-graduate language"),
    (re.compile(r"\buniversity\s+graduate\b", re.I), "university-graduate language"),
    (re.compile(r"\bearly[ -]career\b", re.I), "early-career language"),
    (re.compile(r"\bentry[ -]level\b", re.I), "entry-level language"),
    (re.compile(r"\brecent\s+graduates?\b", re.I), "recent-graduate language"),
    (re.compile(r"\bgraduate\s+program(?:me)?\b", re.I), "graduate-program language"),
    (re.compile(r"\bgraduate\b(?!\s+degree)", re.I), "graduate language"),
    (re.compile(r"\bbachelor(?:'s|s)?(?:\s+degree)?\b", re.I), "bachelor's eligibility"),
    (re.compile(r"\bgraduat(?:e|ing|ion)[^.!?]{0,60}\b202[67]\b", re.I), "compatible graduation window"),
    (re.compile(r"\bcampus\b", re.I), "campus-hiring language"),
    (re.compile(r"\b(?:2027\s+(?:graduate|grad|start|starts)|class\s+of\s+2027)\b", re.I), "2027 graduate/start language"),
    (re.compile(r"\b0\s*(?:-|–|to)\s*[12]\s+years?\b", re.I), "0–2 years experience"),
    (re.compile(r"\b(?:software\s+engineer|sde|engineer)\s*(?:[-–—]\s*)?i\b", re.I), "level-I title"),
    (re.compile(r"\bjunior\b", re.I), "junior title/language"),
    (re.compile(r"\bassociate\b", re.I), "associate title/language"),
]

_EXPERIENCED = [
    re.compile(r"\b(?:minimum|at\s+least|requires?)\s+(?:of\s+)?(?:[3-9]|\d{2})\+?\s+years?\b", re.I),
    re.compile(r"\b(?:[3-9]|\d{2})\+\s+years?\s+of\s+(?:professional|industry|work|software\s+development)\s+experience\b", re.I),
]


def classify(job: Job) -> Match | None:
    """Bias toward notification while honoring affirmative exclusions."""
    title = job.title or ""
    description = job.description or ""
    combined = f"{title}\n{description}"

    if _INTERNSHIP_TITLE.search(title):
        return None
    if _INTERNSHIP_DESCRIPTION.search(description):
        return None
    if not _TECHNICAL.search(combined):
        return None
    if _SENIOR_TITLE.search(title) and not re.search(r"\bmember\s+of\s+technical\s+staff\b", title, re.I):
        return None
    if any(pattern.search(combined) for pattern in _EXPERIENCED):
        return None

    for pattern, reason in _EARLY_SIGNALS:
        if pattern.search(combined):
            return Match(MatchCategory.NEW_GRAD_MATCH, reason)

    return Match(
        MatchCategory.POSSIBLE_NEW_GRAD_MATCH,
        "relevant technical role with no affirmative seniority exclusion",
    )

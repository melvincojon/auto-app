from __future__ import annotations

import re

from .models import Job, Match, MatchCategory


# Role relevance is intentionally title-led. Job descriptions routinely mention
# engineers that an unrelated hire would merely work with.
_TECHNICAL_TITLE = re.compile(
    r"\b(?:"
    r"software\s+(?:development\s+)?engineer|software\s+developer|"
    r"software\s+engineering\s+associate|software\s+engineer|developer|"
    r"sde(?:\s+i)?|backend\s+engineer|back-end\s+engineer|"
    r"infrastructure\s+engineer|platform\s+engineer|systems?\s+engineer|"
    r"site\s+reliability\s+engineer|sre|devops\s+engineer|"
    r"full[ -]?stack\s+(?:engineer|developer)|flight\s+software\s+engineer|"
    r"forward\s+deployed(?:\s+ai)?\s+engineer|applied\s+research\s+engineer|"
    r"machine\s+learning\s+engineer|ml\s+engineer|ai\s+engineer|"
    r"member\s+of\s+technical\s+staff|associate\s+(?:software\s+)?engineer|"
    r"junior\s+(?:software\s+)?engineer|engineer\s*(?:[-–—]\s*)?i|"
    r"quantitative\s+developer|quant\s+developer|quantitative\s+technologist"
    r")\b",
    re.I,
)

_IRRELEVANT_TITLE = re.compile(
    r"\b(?:hardware|electrical|mechanical|silicon)"
    r"(?:\s+(?:systems?|validation))?\s+engineer\b|"
    r"\b(?:pre[ -]?sales|solutions?\s+consult(?:ant|ing)|"
    r"digital\s+solution\s+engineering)\b",
    re.I,
)

_INTERNSHIP_TITLE = re.compile(r"\b(?:intern(?:ship)?|co[ -]?op)\b", re.I)
_INTERNSHIP_DESCRIPTION = re.compile(
    r"\b(?:this|our|paid|summer|winter|spring|fall)\s+"
    r"(?:software\s+engineering\s+)?intern(?:ship)?\b|"
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
_MEMBER_OF_TECHNICAL_STAFF = re.compile(r"\bmember\s+of\s+technical\s+staff\b", re.I)

_GRADUATE_PROGRAM_TITLE = re.compile(
    r"\b(?:(?:202[67]|technology|university)\s+)?graduate\s+program(?:me)?\b|"
    r"\b(?:new[ -](?:college\s+)?grad(?:uate)?|early[ -]career)\s+program(?:me)?\b",
    re.I,
)
_GRADUATE_ROLE_DESCRIPTION = re.compile(
    r"\b(?:join|work|start|serve)\b[^.!?]{0,60}\bas\s+(?:an?\s+)?(?:"
    r"software\s+(?:development\s+)?engineer|software\s+developer|developer|"
    r"quantitative\s+developer|quant\s+developer|quantitative\s+technologist"
    r")\b",
    re.I,
)

_EARLY_SIGNALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bnew\s+(?:college\s+)?grad(?:uate)?s?\b", re.I), "new-graduate language"),
    (re.compile(r"\bgraduate\s+software\s+engineer\b", re.I), "graduate software engineer title"),
    (re.compile(r"\b(?:university|recent)\s+graduates?\b", re.I), "university/recent-graduate language"),
    (re.compile(r"\bearly[ -]career\b", re.I), "early-career language"),
    (re.compile(r"\bentry[ -]level\b", re.I), "entry-level language"),
    (re.compile(r"\bgraduate\s+program(?:me)?\b", re.I), "graduate-program language"),
    (re.compile(r"\bcampus\s+(?:hire|hiring|recruit(?:ing|ment))\b", re.I), "campus-hiring language"),
    (re.compile(r"\b(?:class\s+of\s+2027|2027\s+(?:graduate|grad|start(?:s|ing)?))\b", re.I), "2027 graduate/start language"),
    (
        re.compile(
            r"\b(?:graduat(?:e|ing|ion)|degree|start(?:ing)?)\b[^.!?]{0,80}"
            r"\b(?:spring|summer|fall|winter|may|june|dec(?:ember)?|aug(?:ust)?)?\s*202[67]\b|"
            r"\b(?:spring|summer|fall|winter|may|june|dec(?:ember)?|aug(?:ust)?)\s*202[67]\b"
            r"[^.!?]{0,80}\b(?:graduat(?:e|ing|ion)|degree|start(?:ing)?)\b",
            re.I,
        ),
        "compatible graduation window",
    ),
    (
        re.compile(
            r"\b(?:fall|spring|summer|winter)\s+2026\s+(?:or|and|through|to|[-–—/])\s+"
            r"(?:fall|spring|summer|winter)\s+2027\b",
            re.I,
        ),
        "compatible graduation window",
    ),
    (re.compile(r"\bfinal\s+year\s+of\s+(?:study|school|an?\s+equivalent)\b", re.I), "final-year eligibility"),
    (re.compile(r"\bdegree\s+(?:was\s+)?earned\s+within\s+the\s+(?:past|last)\s+year\b", re.I), "recent degree"),
    (re.compile(r"\b0\s*(?:-|–|—|to)\s*[12]\s+years?\b", re.I), "0–2 years experience"),
    (re.compile(r"\bup\s+to\s+2\s+years?\b", re.I), "up to 2 years experience"),
]
_EARLY_TITLE_SIGNALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:software\s+engineer|sde|engineer)\s*(?:[-–—]\s*)?i\b", re.I), "level-I title"),
    (re.compile(r"\bjunior\b", re.I), "junior title"),
    (re.compile(r"\bassociate\b", re.I), "associate title"),
]

# These are strong, non-city-only signals. Unknown locations remain eligible so
# providers that emit values such as "Remote" or "Multiple Locations" do not
# cause false negatives.
_US_COUNTRY = re.compile(r"\b(?:united\s+states(?:\s+of\s+america)?|u\.?s\.?(?:a\.?)?)\b", re.I)
_US_STATE_CODE = re.compile(
    r"(?<![A-Za-z])(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IA|KS|KY|LA|"
    r"ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|"
    r"SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)(?![A-Za-z])"
)
_US_STATE_NAME = re.compile(
    r"\b(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|"
    r"delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
    r"kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
    r"mississippi|missouri|montana|nebraska|nevada|new\s+hampshire|new\s+jersey|"
    r"new\s+mexico|new\s+york|north\s+carolina|north\s+dakota|ohio|oklahoma|"
    r"oregon|pennsylvania|rhode\s+island|south\s+carolina|south\s+dakota|"
    r"tennessee|texas|utah|vermont|virginia|washington|west\s+virginia|"
    r"wisconsin|wyoming|district\s+of\s+columbia)\b",
    re.I,
)
_INDIANA_LOCATION = re.compile(
    r"\b(?:indianapolis|fort\s+wayne|bloomington|west\s+lafayette|south\s+bend)\s*,?\s+IN\b",
    re.I,
)
_FOREIGN_LOCATION = re.compile(
    r"\b(?:canada|india|israel|united\s+kingdom|u\.?k\.?|england|scotland|wales|"
    r"ireland|germany|france|spain|italy|portugal|netherlands|belgium|sweden|"
    r"norway|denmark|finland|poland|romania|switzerland|austria|czechia|"
    r"singapore|china|japan|south\s+korea|australia|new\s+zealand|mexico|brazil|"
    r"argentina|colombia|costa\s+rica|philippines|vietnam|indonesia|malaysia|"
    r"united\s+arab\s+emirates|u\.?a\.?e\.?|saudi\s+arabia|south\s+africa)\b",
    re.I,
)
_INDIA_LOCATION = re.compile(
    r"\b(?:bengaluru|bangalore|hyderabad|chennai|pune|mumbai|gurugram|gurgaon|"
    r"new\s+delhi|noida)\b|(?<![A-Za-z])(?:KA|TS)(?![A-Za-z])|"
    r"(?<![A-Za-z])IN(?:\s*[,;-]|\s+(?:KA|TS|bengaluru|bangalore|hyderabad))(?![A-Za-z])",
    re.I,
)

_EXPERIENCE_REQUIREMENT = re.compile(
    r"(?:"
    r"\b(?:minimum(?:\s+of)?|at\s+least)\s+(?:[2-9]|\d{2,})\+?\s+years?"
    r"(?:\s+of)?\s+(?:non[ -]?internship\s+)?"
    r"(?:(?:relevant|professional|industry|work|technical)\s+){0,3}"
    r"(?:experience|engineering(?:\s+experience)?|software\s+(?:engineering|development))\b|"
    r"\b(?:[2-9]|\d{2,})\+\s+years?(?:\s+of)?\s+"
    r"(?:non[ -]?internship\s+)?(?:relevant\s+)?(?:professional\s+)?"
    r"(?:software\s+(?:engineering|development)|engineering|industry|technical\s+pre[ -]?sales|"
    r"professional\s+experience|relevant\s+(?:industry\s+)?experience)\b|"
    r"\b(?:[2-9]|\d{2,})\+\s+(?:years?\s+)?(?:relevant\s+)?industry\s+experience\b|"
    r"\b(?:[2-9]|\d{2,})\+\s+(?:years?\s+)?technical\s+pre[ -]?sales\b|"
    r"\b(?:[2-9]|\d{2,})\s+years?(?:\s+of)?\s+"
    r"(?:non[ -]?internship\s+)?(?:relevant\s+)?(?:professional\s+)?"
    r"(?:software\s+(?:engineering|development)|engineering|industry|"
    r"professional\s+experience|relevant\s+(?:industry\s+)?experience)\b"
    r")",
    re.I,
)
_ALLOWED_EXPERIENCE_RANGE_PREFIX = re.compile(
    r"(?:\b0\s*(?:-|–|—|to)\s*|\bup\s+to\s*)$",
    re.I,
)
_OTHER_PERSON_EXPERIENCE = re.compile(
    r"(?:our|the|their)\s+team|team\s+(?:has|with|brings)|"
    r"(?:work|collaborate|partner)\s+with\s+(?:senior\s+)?(?:engineers?|colleagues?)|"
    r"(?:manager|mentor|colleague|founder|leadership)\s+(?:has|with|brings)|"
    r"higher[- ]level\s+(?:roles?|positions?)|roles?\s+at\s+higher\s+levels?",
    re.I,
)


def _us_location_eligible(location: str | None) -> bool:
    if not location or not location.strip():
        return True

    if (
        _US_COUNTRY.search(location)
        or _US_STATE_CODE.search(location)
        or _US_STATE_NAME.search(location)
        or _INDIANA_LOCATION.search(location)
    ):
        return True
    return not (_FOREIGN_LOCATION.search(location) or _INDIA_LOCATION.search(location))


def _requires_experienced_candidate(description: str) -> bool:
    for match in _EXPERIENCE_REQUIREMENT.finditer(description):
        prefix = description[max(0, match.start() - 12) : match.start()]
        if _ALLOWED_EXPERIENCE_RANGE_PREFIX.search(prefix):
            continue
        before = max(description.rfind(mark, 0, match.start()) for mark in ".;\n•")
        after_candidates = [
            position
            for mark in ".;\n•"
            if (position := description.find(mark, match.end())) >= 0
        ]
        after = min(after_candidates, default=len(description))
        context = description[before + 1 : after]
        if _OTHER_PERSON_EXPERIENCE.search(context):
            continue
        return True
    return False


def _has_explicit_seniority(title: str) -> bool:
    # "Staff" is part of the base MTS role name, not a level by itself. Any
    # seniority word elsewhere in the title remains visible and is rejected.
    title_without_mts = _MEMBER_OF_TECHNICAL_STAFF.sub("", title)
    return bool(_SENIOR_TITLE.search(title_without_mts))


def classify(job: Job) -> Match | None:
    """Bias toward notification while honoring affirmative exclusions."""
    title = job.title or ""
    description = job.description or ""
    combined = f"{title}\n{description}"

    if _INTERNSHIP_TITLE.search(title) or _INTERNSHIP_DESCRIPTION.search(description):
        return None
    if not _us_location_eligible(job.location):
        return None
    relevant_title = bool(_TECHNICAL_TITLE.search(title))
    graduate_program_role = bool(
        _GRADUATE_PROGRAM_TITLE.search(title)
        and _GRADUATE_ROLE_DESCRIPTION.search(description)
    )
    if _IRRELEVANT_TITLE.search(title) or not (relevant_title or graduate_program_role):
        return None
    if _has_explicit_seniority(title):
        return None
    if _requires_experienced_candidate(description):
        return None

    for pattern, reason in _EARLY_TITLE_SIGNALS:
        if pattern.search(title):
            return Match(MatchCategory.NEW_GRAD_MATCH, reason)
    for pattern, reason in _EARLY_SIGNALS:
        if pattern.search(combined):
            return Match(MatchCategory.NEW_GRAD_MATCH, reason)

    return Match(
        MatchCategory.POSSIBLE_NEW_GRAD_MATCH,
        "relevant technical role with no affirmative seniority exclusion",
    )

"""Pull structured facts out of free-text postings: required experience, qualification, and a role key.

These are heuristics over text the employer wrote. They never invent values: if nothing is stated, the field
stays empty ("not specified"). Everything extracted is editable in the post composer before sharing."""
import hashlib
import math
import re

# ------------------------------------------------------------------ experience
_NUM = r"(\d{1,2}(?:\.\d)?)"
_YRS = r"(?:years?|yrs?)"
_RANGE = re.compile(rf"{_NUM}\s*\+?\s*(?:-|–|—|to)\s*{_NUM}\s*\+?\s*{_YRS}", re.I)
_PLUS = re.compile(rf"{_NUM}\s*\+\s*{_YRS}", re.I)
_MIN = re.compile(rf"(?:minimum|min\.?|at\s+least|atleast|more\s+than|over)\s*(?:of\s*)?{_NUM}\s*\+?\s*{_YRS}", re.I)
_PLAIN = re.compile(rf"{_NUM}\s*{_YRS}", re.I)
_FRESHER = re.compile(r"\b(freshers?|no\s+(?:prior\s+)?(?:work\s+)?experience\s+(?:is\s+)?required)\b", re.I)
_REJECT_AFTER = re.compile(r"\s*(old|ago|of\s+age|warranty|in\s+business)\b", re.I)
_REJECT_BEFORE = re.compile(r"(founded|since|established|over\s+the\s+(?:last|past)|for\s+the\s+(?:last|past)|"
                            r"history\s+of|aged?|anniversary|celebrat\w*)\W*(?:\w+\W+){0,2}$", re.I)
_EXP_WORD = re.compile(r"\b(exp|experience|experienced)\b", re.I)
_AFTER_OK = re.compile(r"\s*(?:of|in|working|building|developing|designing|hands|professional|industry|relevant|"
                       r"related|post|managing|leading|selling|software|sales|engineering|as)\b", re.I)


def _ok(text, start, end):
    before, after = text[max(0, start - 60):start], text[end:end + 60]
    if _REJECT_AFTER.match(after) or _REJECT_BEFORE.search(before):
        return False
    return bool(_EXP_WORD.search(before) or _EXP_WORD.search(after[:40]) or _AFTER_OK.match(after))


def extract_experience(text):
    """Return (min_years, max_years) or (None, None). max is None for open-ended ("3+ years")."""
    if not text:
        return None, None
    taken = []  # spans already used, so "3-5 years" is not also read as "5 years"
    mins, maxes = [], []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for m in _RANGE.finditer(text):
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi <= 30 and _ok(text, m.start(), m.end()):
            mins.append(math.floor(lo)); maxes.append(math.ceil(hi)); taken.append(m.span())
    for rx in (_MIN, _PLUS, _PLAIN):
        for m in rx.finditer(text):
            if not free(*m.span()):
                continue
            val = float(m.group(1))
            if val <= 30 and _ok(text, m.start(), m.end()):
                mins.append(math.floor(val)); taken.append(m.span())
    if _FRESHER.search(text):
        mins.append(0)
        if not maxes:
            maxes.append(1)
    if not mins:
        return None, None
    lo = min(mins)
    hi = max(maxes) if maxes else None
    if hi is not None and hi < lo:
        hi = None
    return lo, hi


def experience_label(lo, hi):
    """Text used on the dashboard and in posts: '3 - 6 years', '3+ years', 'Fresher'."""
    if lo is None:
        return ""
    if lo == 0 and (hi is None or hi <= 1):
        return "Fresher" if hi == 0 or hi is None else "Fresher (0 - 1 years)"
    if hi is None:
        return f"{lo}+ years"
    if hi == lo:
        return f"{lo} year{'s' if lo != 1 else ''}"
    return f"{lo} - {hi} years"


# ------------------------------------------------------------------ qualification
_DEGREE_WORDS = re.compile(
    r"\b(bachelor'?s?|master'?s?|degree|graduate|graduation|post[- ]?graduate|undergraduate|diploma|doctorate|"
    r"ph\.?\s?d|b\.\s?tech|btech|m\.\s?tech|mtech|b\.\s?sc|bsc|m\.\s?sc|msc|b\.\s?com|bcom|m\.\s?com|mcom|"
    r"chartered\s+accountant)\b", re.I)
_DEGREE_ACRONYMS = re.compile(r"\b(B\.?E|M\.?E|B\.?S|M\.?S|BA|BBA|BCA|MCA|MBA|PGDM|CA|CPA|CFA|ACCA|CS)\b")
_NOT_A_REQUIREMENT = re.compile(r"\b(regardless|irrespective|equal opportunity|discriminat)", re.I)


def extract_qualification(text, limit=180):
    """The first line/sentence that states a degree or diploma, e.g. "Bachelor's degree in Marketing"."""
    if not text:
        return ""
    units = []
    for line in text.splitlines():
        units += [u for u in re.split(r"(?<=[.;])\s+", line) if u.strip()]
    for unit in units:
        if _NOT_A_REQUIREMENT.search(unit):
            continue
        if _DEGREE_WORDS.search(unit) or _DEGREE_ACRONYMS.search(unit):
            clean = re.sub(r"^[\s•\-*–·]+", "", unit).strip()
            clean = re.sub(r"^(qualifications?|education(?:al)?(?:\s+qualification)?|requirements?)\s*[:\-–]\s*", "",
                           clean, flags=re.I)
            clean = clean.rstrip(" .;")
            if len(clean) > limit:
                clean = clean[:limit].rsplit(" ", 1)[0] + "…"
            return clean
    return ""


# ------------------------------------------------------------------ role key (summary reuse)
def role_hash(title, description):
    """Same title + same description = same role, wherever and however often it is posted."""
    norm = lambda s: " ".join((s or "").lower().split())
    return hashlib.sha256(f"{norm(title)}\n{norm(description)}".encode("utf-8")).hexdigest()

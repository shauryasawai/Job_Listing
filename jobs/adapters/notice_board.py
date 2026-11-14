"""Official government recruitment pages ("notice boards") and RSS/Atom feeds.

Government bodies (UPSC, PSUs, banks, state commissions...) publish vacancies as notices, usually PDFs linked
from a recruitment page, not through job APIs. This adapter reads such a page and keeps only recruitment
notices. It needs no per-site code: it looks at every link, takes the title from the link text or, when the
link text is just "(1.49 MB)" / "Download", from the surrounding list item or table row, and filters by
recruitment wording. Results, admit cards, answer keys, syllabi and site menus are dropped.

It respects robots.txt, makes a single request per run, and does not run JavaScript: pages that build their
list with JavaScript (e.g. ssc.gov.in) cannot be read and are reported as such.
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone as dt_tz
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

from django.conf import settings
from django.utils.dateparse import parse_datetime

from .base import BaseAdapter, RawJob
from .http import BlockedError, FetchError, _get_session
from . import http as http_mod
from .text import clean_text, html_to_text
from ..geo import REMOTE, cities_for

RECRUIT = re.compile(
    r"\b(recruit\w*|vacanc\w*|advertisements?|advt\b\.?|employment notice|notification for|posts? of|engagement|"
    r"walk[- ]?in|appointment|deputation|contract(?:ual)? basis|apprentice\w*|internships?|trainees?|"
    r"faculty|positions?|jobs?|hiring|careers?|selection of|filling up|direct recruitment|openings?)\b", re.I)
EXCLUDE = re.compile(
    r"\b(results?|answer[- ]keys?|admit[- ]cards?|e-?admit|call[- ]letters?|syllabus|marks|cut[- ]?offs?|"
    r"interview[- ]schedules?|schedule of interview|corrigend\w*|addend\w*|tenders?|rti\b|"
    r"exam(?:ination)? calendar|question papers?|merit[- ]lists?|selection[- ]lists?|scrutiny|applicants'? list|"
    r"status of|archives?|log ?in|sign[- ]?in|faqs?|help ?(?:line|desk)|contact us|sitemap|privacy|disclaimer)\b",
    re.I)
GENERIC = re.compile(
    r"^\W*([\d.,]+\s*(kb|mb|bytes?)|download\w*|click here|here|view|pdf|details?|more|read more|"
    r"apply(?: online| now)?|english|hindi|link|open|notification|new)\W*$", re.I)
TRAILING = re.compile(r"[\s\-–|:]*\b(download\w*|click here|view|pdf|details?|read more|apply online|here)\W*$", re.I)
SIZE = re.compile(r"\(\s*[\d.,]+\s*(kb|mb|bytes?)\s*\)", re.I)
DOC_EXT = re.compile(r"\.(pdf|docx?|xlsx?|rtf)(?:[?#]|$)", re.I)
SKIP_ATTR = re.compile(r"(^|[\s_-])(nav|navbar|menu|footer|header|breadcrumbs?|sidebar|skip|social|top-?bar)([\s_-]|$)",
                       re.I)
SKIP_TAGS = {"nav", "header", "footer"}
CONTEXT_TAGS = {"li", "tr", "p", "dd", "dt", "article", "h1", "h2", "h3", "h4", "h5", "h6", "div", "td", "span"}
VOID = {"br", "img", "hr", "input", "meta", "link", "wbr", "source", "area", "base", "col", "embed", "param", "track"}
IGNORE = {"script", "style", "noscript", "template", "select", "option"}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DATE_NUM = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")
DATE_TXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?[\s-]+(20\d{2})\b", re.I)
LAST_DATE_WORDS = re.compile(r"(last|closing|end)\s+date|till|upto|up to|before|deadline|on or before", re.I)


class _Block:
    __slots__ = ("tag", "parts")

    def __init__(self, tag):
        self.tag, self.parts = tag, []

    @property
    def text(self):
        return clean_text(" ".join(self.parts)).replace("\n", " ")


class _LinkCollector(HTMLParser):
    """Collects every <a href> with its own text, the text of its innermost list item/row/paragraph,
    and whether it sits inside navigation (menus, header, footer)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.links, self.current, self.ignore = [], [], None, 0

    def _in_skip(self):
        return any(skip for _, skip, _ in self.stack)

    def _innermost_block(self):
        for tag, _, block in reversed(self.stack):
            if block is not None and tag != "span":
                return block
        return None

    def handle_starttag(self, tag, attrs):
        if tag in IGNORE:
            self.ignore += 1
            return
        if tag in VOID:
            return
        a = dict(attrs)
        marker = f"{a.get('class') or ''} {a.get('id') or ''}"
        skip = tag in SKIP_TAGS or a.get("role") == "navigation" or bool(SKIP_ATTR.search(marker))
        self.stack.append((tag, skip, _Block(tag) if tag in CONTEXT_TAGS else None))
        if tag == "a" and a.get("href"):
            self.current = {"href": a["href"].strip(), "parts": [], "title": (a.get("title") or "").strip(),
                            "block": self._innermost_block(), "skip": self._in_skip()}

    def handle_endtag(self, tag):
        if tag in IGNORE:
            self.ignore = max(0, self.ignore - 1)
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag == "a" and self.current is not None:
            self.links.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.ignore:
            return
        for _, _, block in self.stack:
            if block is not None:
                block.parts.append(data)
        if self.current is not None:
            self.current["parts"].append(data)


def _parse_date(text, prefer_last=False):
    """First date in text (dd/mm/yyyy, dd.mm.yyyy, '12 June 2026'). Indian day-first convention."""
    found = []
    for m in DATE_NUM.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        found.append((m.start(), d, mo, y))
    for m in DATE_TXT.finditer(text):
        found.append((m.start(), int(m.group(1)), _MONTHS[m.group(2).lower()[:3]], int(m.group(3))))
    found.sort()
    for start, d, mo, y in found:
        is_last = bool(LAST_DATE_WORDS.search(text[max(0, start - 30):start]))
        if is_last != prefer_last:
            continue
        try:
            return datetime(y, mo, d, tzinfo=dt_tz.utc)
        except ValueError:
            continue
    return None


def _same_page(a, b):
    sa, sb = urlsplit(a), urlsplit(b)
    return (sa.netloc.lower(), sa.path.rstrip("/"), sa.query) == (sb.netloc.lower(), sb.path.rstrip("/"), sb.query)


def extract_notices(html, page_url, pdf_only=True):
    """[(title, absolute_url, context_text)] for recruitment notices on an HTML page."""
    parser = _LinkCollector()
    parser.feed(html)
    parser.close()
    out, seen = [], set()
    for link in parser.links:
        href = link["href"]
        if link["skip"] or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        url = urljoin(page_url, href)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or _same_page(url, page_url):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        own = clean_text(" ".join(link["parts"])).replace("\n", " ")
        block = link["block"].text if link["block"] is not None else ""
        if own and not GENERIC.match(own) and len(own) >= 6:
            title = own
        elif block and len(block) <= 400:
            title = SIZE.sub("", block).strip()
            for _ in range(2):
                title = TRAILING.sub("", title).strip()
        else:
            title = link["title"] or own
        title = re.sub(r"\s+", " ", SIZE.sub("", title)).strip(" -–|:·•")
        if len(title) < 6:
            continue
        is_doc = bool(DOC_EXT.search(url))
        haystack = f"{title} {block[:400]}"
        if pdf_only and not is_doc:
            continue
        if not RECRUIT.search(haystack) or EXCLUDE.search(title):
            continue
        if url in seen:
            continue
        seen.add(url)
        context = SIZE.sub("", block if block and len(block) <= 600 else title).strip()
        for _ in range(2):
            context = TRAILING.sub("", context).strip()
        out.append((title[:300], url, context))
    return out


def _xml_text(el, *names):
    for child in el:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names:
            if tag == "link" and child.get("href"):
                return child.get("href")
            return (child.text or "").strip()
    return ""


def parse_feed(xml_text):
    """[(title, url, description, published)] from an RSS 2.0 or Atom feed."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"The feed is not valid XML ({exc}).")
    items = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag not in ("item", "entry"):
            continue
        title = _xml_text(el, "title")
        link = _xml_text(el, "link", "guid")
        desc = html_to_text(_xml_text(el, "description", "summary", "content"))
        raw_date = _xml_text(el, "pubdate", "published", "updated", "date")
        published = None
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                published = parse_datetime(raw_date)
        if title and link:
            items.append((clean_text(title).replace("\n", " "), link.strip(), desc, published))
    return items


# ------------------------------------------------------------------ robots.txt (cached per host for 12 hours)
_ROBOTS = {}


def robots_allows(url):
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    cached = _ROBOTS.get(host)
    if cached is None or time.time() - cached[0] > 12 * 3600:
        rp = robotparser.RobotFileParser()
        try:
            resp = _get_session().get(f"{host}/robots.txt",
                                      timeout=(settings.HTTP_CONNECT_TIMEOUT, settings.HTTP_READ_TIMEOUT))
            lines = resp.text.splitlines() if resp.status_code == 200 else []
        except Exception:  # unreachable robots.txt: treated as "no rules" (standard behaviour)
            lines = []
        rp.parse(lines)
        cached = (time.time(), rp)
        _ROBOTS[host] = cached
    return cached[1].can_fetch(settings.USER_AGENT, url)


class NoticeBoardAdapter(BaseAdapter):
    key = "notice_board"
    label = "Government notice page"

    def fetch_jobs(self):
        cfg = self.source.configuration_json or {}
        url = (cfg.get("url") or "").strip()
        if not url:
            raise FetchError("No notice page URL configured for this source.")
        if not robots_allows(url):
            raise BlockedError("This site's robots.txt asks automated tools not to read that page, so it is skipped.")
        text, ctype, final_url = http_mod.get_text(url)
        head = text.lstrip()[:300].lower()
        org = self.source.company_name
        if "xml" in ctype or head.startswith("<?xml") or "<rss" in head or "<feed" in head:
            jobs = [self._job(title, link, desc or title, published, org)
                    for title, link, desc, published in parse_feed(text)
                    if RECRUIT.search(f"{title} {desc[:300]}") and not EXCLUDE.search(title)]
        else:
            jobs = [self._job(title, link, context, _parse_date(context), org)
                    for title, link, context in extract_notices(text, final_url, bool(cfg.get("pdf_only", True)))]
            if not jobs and ("enable javascript" in text.lower() or 'id="root"' in text or "id='root'" in text):
                raise FetchError("No notices found. This page seems to build its list with JavaScript, which this "
                                 "tool does not run. Use the site's RSS feed or a page that lists the notices directly.")
        return jobs

    @staticmethod
    def _job(title, url, context, posted, org):
        last = _parse_date(context, prefer_last=True)
        desc = context if context and context != title else ""
        if last and "last date" not in desc.lower():
            desc = f"{desc}\nLast date: {last:%d %b %Y}".strip()
        desc = f"{desc}\nOfficial notice by {org}. Open it for eligibility, age limit, fees and how to apply.".strip()
        return RawJob(
            title=title,
            url=url,
            description=desc,
            location=", ".join(c for c in cities_for([title, context]) if c != REMOTE) or "India",
            country="IN",
            employment_type="Contract" if re.search(r"\bcontract", title, re.I) else "",
            department=org,
            posted_at=posted,
        )

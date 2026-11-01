"""HTML -> clean plain text helpers (stdlib only)."""
import html
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "table"}
_SKIP = {"script", "style"}


class _Extractor(HTMLParser):
    """HTML -> text with sensible spacing: blank line between blocks, one line per bullet."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def _break(self, n):
        """Ensure the output ends with at least n newlines (never at the very start)."""
        if not self.parts:
            return
        tail = "".join(self.parts[-4:])
        have = len(tail) - len(tail.rstrip("\n"))
        if have < n:
            self.parts.append("\n" * (n - have))

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "li":
            self._break(1)
            self.parts.append("• ")
        elif tag in ("br", "tr", "ul", "ol"):
            self._break(1)
        elif tag in _BLOCK:
            self._break(2)

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif re.fullmatch(r"h[1-6]", tag) or tag in ("ul", "ol", "tr"):
            self._break(1)
        elif tag in _BLOCK and tag not in ("li", "br"):
            self._break(2)

    def handle_data(self, data):
        if self._skip:
            return
        if not data.strip():
            if self.parts and not self.parts[-1].endswith(("\n", " ")):
                self.parts.append(" ")
            return
        self.parts.append(data)


def clean_text(text):
    """Normalise whitespace but keep paragraph breaks."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(markup):
    if not markup:
        return ""
    parser = _Extractor()
    parser.feed(markup)
    parser.close()
    return clean_text("".join(parser.parts))


def unescape_html_content(content):
    """Greenhouse returns HTML as HTML-entities (&lt;p&gt;...). Decode until real tags appear."""
    if not content:
        return ""
    decoded = html.unescape(content)
    if "<" not in decoded and "&lt;" in decoded:  # double-escaped
        decoded = html.unescape(decoded)
    return decoded

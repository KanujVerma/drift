"""Candidate extraction used only by isolated historical evaluation.

A nonempty match is a heuristic, not a claim that it is representative or
sufficient research. The unmodified filing extractor remains the baseline.
"""

import re
from html.parser import HTMLParser


class _VisibleText(HTMLParser):
    _blocks = frozenset({"p", "div", "tr", "li", "br", "h1", "h2", "h3"})
    _void = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )
    _ignored = frozenset({"head", "script", "style", "ix:hidden"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        style = re.sub(r"\s+", "", (values.get("style") or "").lower())
        hidden = (
            tag in self._ignored
            or "hidden" in values
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if self.hidden_depth:
            if tag not in self._void:
                self.hidden_depth += 1
            return
        if hidden:
            if tag not in self._void:
                self.hidden_depth = 1
            return
        if tag in self._blocks:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in self._blocks:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(re.sub(r"\s+", " ", data))


def substantive_excerpt(body: str, limit: int = 900) -> str:
    """Find one visible financial narrative; return empty when none matches."""
    parser = _VisibleText()
    parser.feed(body)
    for line in "".join(parser.parts).splitlines():
        paragraph = re.sub(r"\s+", " ", line).strip()[:limit]
        if (
            len(paragraph) >= 90
            and len(paragraph.split()) >= 15
            and re.search(
                r"\b(revenue|revenues|sales|earnings|income|expenses|cash flow)\b",
                paragraph,
                re.I,
            )
            and re.search(
                r"\b(increased|decreased|grew|declined|higher|lower|driven|compared)\b",
                paragraph,
                re.I,
            )
            and re.search(r"\d", paragraph)
            and not re.search(
                r"\b(may|could|would|potential|future|assumes?|assuming|estimated?)\b",
                paragraph,
                re.I,
            )
        ):
            return paragraph
    return ""

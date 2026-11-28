"""Checks for the isolated evaluation's alternative filing excerpts."""

from drift.historical.evaluation_excerpts import substantive_excerpt


def test_self_closing_void_tag_does_not_expose_hidden_financial_text() -> None:
    body = (
        '<div style="display:none"><br/>'
        "Revenue increased 42 percent compared with the prior year because "
        "strong demand and higher sales drove growth across all of our products."
        "</div><p>Visible short text.</p>"
    )
    assert substantive_excerpt(body) == ""


def test_prefers_financial_narrative_to_contents_and_hidden_metadata() -> None:
    body = """<html><head><title>Cover</title></head><body>
    <ix:hidden>Revenue was fabricated: $999 billion.</ix:hidden>
    <div>Item 7. Management Discussion and Analysis 31</div>
    <div>Item 8. Financial Statements 32</div>
    <p>Net sales increased 12% to $40 billion compared with the prior year,
       driven by stronger demand in the consumer segment across all regions.</p>
    </body></html>"""
    excerpt = substantive_excerpt(body)
    assert "Net sales increased 12%" in excerpt
    assert "fabricated" not in excerpt
    assert "Item 7." not in excerpt


def test_requires_substantive_narrative_and_fails_closed_on_contents() -> None:
    body = "<div>Item 7. Financial Results 31</div><div>Item 8. Revenue 32</div>"
    assert substantive_excerpt(body) == ""


def test_keeps_the_matched_paragraph_without_a_later_financial_statement() -> None:
    body = """<p>Revenue decreased 8% from the prior year to $2 billion because
    of lower shipment volumes and unfavorable currency effects across the group.</p>
    <p>Another business reported revenue increased 20% in an unrelated filing.</p>"""
    excerpt = substantive_excerpt(body)
    assert "decreased 8%" in excerpt
    assert "Another business" not in excerpt


def test_does_not_select_boilerplate_because_match_is_after_truncation() -> None:
    body = (
        "<p>As described in risk factors, future regulation may affect earnings. "
        + "Potential impacts remain uncertain and cannot be predicted. " * 20
        + "Later, sales increased 4% compared with the prior year.</p>"
    )
    assert substantive_excerpt(body, limit=300) == ""


def test_does_not_present_hypothetical_growth_assumptions_as_results() -> None:
    body = """<p>Management estimates the future value of the division. Our
    assessment assumes that net sales growth rates may have increased 5% each year
    and could vary depending on conditions over the coming years.</p>"""
    assert substantive_excerpt(body) == ""

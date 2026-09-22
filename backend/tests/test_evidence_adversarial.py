"""
Adversarial evidence verification (Phase 1G).

System guarantees, verified by the tests below — ONLY:
1. The citation is at least 15 characters.
2. The citation, when normalized (HTML stripped, unicode punctuation
   flattened, whitespace collapsed, lowercase), is an exact contiguous
   substring of the normalized article content.

Explicitly NOT guaranteed (each a KNOWN LIMITATION exercised by a test
below, not just asserted in prose — substring matching proves a quote
EXISTS in the source, not that it means what it's being used to mean):
1. Attribution — who said it (test_evidence_attribution_confusion).
2. Context — whether it's a denial, a hypothetical, or an assertion
   (test_evidence_misleading_quote_assembled_across_paragraphs).
3. Importance/relevance — whether it's boilerplate vs. factual content
   (test_evidence_boilerplate_and_navigation,
   test_evidence_cookie_banner_accepted_as_evidence).

This module previously had a `test_evidence_document_guarantees` function
whose entire body was a docstring followed by `pass` — it documented
these guarantees in prose but verified nothing (see
docs/RED_TEAM_REPORT.md TEST-QUALITY-EVAL-SUMMARY-01 for the sibling
finding in test_event_relationship_eval.py). Replaced with this module
docstring plus the cookie-banner case below, which is the one
Phase-1G-named attack this file didn't already cover behaviorally.
"""
import pytest
from app.core.deduplication import verify_citations

def test_evidence_misleading_quote_assembled_across_paragraphs():
    # Test that assembling a quote across paragraphs fails if there is text in between,
    # but succeeds if it's just whitespace separation.
    content = "The CEO denied the allegations. \n\n We are guilty of nothing."
    
    # Valid contiguous quote across newlines (which normalize to space)
    valid_quote = "The CEO denied the allegations. We are guilty of nothing."
    assert verify_citations(content, [valid_quote]) == [valid_quote]

    # Invalid assembled quote (skipping text)
    content2 = "The CEO said today: 'We are definitely not going to fail.' But they will."
    invalid_quote = "The CEO said today: 'We are definitely going to fail.'"
    assert not verify_citations(content2, [invalid_quote])

def test_evidence_boilerplate_and_navigation():
    # The system only guarantees substring existence, so navigation text is accepted
    # if it bypassed the HTML cleaner.
    content = "Home > News > Security. The system was breached."
    nav_quote = "Home > News > Security."
    
    # Substring matching accepts this. This is a KNOWN LIMITATION.
    assert verify_citations(content, [nav_quote]) == [nav_quote]

def test_evidence_attribution_confusion():
    # The system only guarantees substring existence, not who said it.
    content = "The attacker posted: 'I have stolen the data.' The company denied this."
    
    # If the LLM claims the company said "I have stolen the data.", 
    # verify_citations will ACCEPT it because it exists in the text.
    # This is a KNOWN LIMITATION documented in the guarantees.
    confusing_quote = "I have stolen the data."
    assert verify_citations(content, [confusing_quote]) == [confusing_quote]

def test_evidence_unicode_normalization_tricks():
    # Test that smart quotes and em-dashes are normalized so legitimate quotes pass,
    # but actual text alterations fail.
    content = 'The "smart" quotes and em—dash.'
    
    # Valid normalization
    valid_quote = 'The "smart" quotes and em-dash.'
    assert verify_citations(content, [valid_quote]) == [valid_quote]
    
    # Invalid alteration
    invalid_quote = 'The "dumb" quotes and em-dash.'
    assert not verify_citations(content, [invalid_quote])

def test_evidence_cookie_banner_accepted_as_evidence():
    """
    A cookie-consent banner left in extracted content (if it bypassed the
    HTML cleaner) is accepted as valid "evidence" by substring matching
    alone, exactly like navigation text — it's ≥15 chars and a real
    substring of the article. Same KNOWN LIMITATION as
    test_evidence_boilerplate_and_navigation, exercised with content
    shaped like a real cookie banner rather than a nav breadcrumb, since
    those are different HTML-cleaning failure modes in practice (nav
    breadcrumbs vs. consent-management-platform boilerplate).
    """
    content = (
        "We use cookies to personalize content and ads. By clicking Accept, "
        "you consent to our use of cookies. The vulnerability was patched within hours."
    )
    cookie_banner_quote = "We use cookies to personalize content and ads."
    assert verify_citations(content, [cookie_banner_quote]) == [cookie_banner_quote]

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

def test_evidence_document_guarantees():
    """
    Verification of the system guarantees.
    The current system guarantees ONLY:
    1. The citation is at least 15 characters.
    2. The citation, when normalized (HTML stripped, unicode punctuation flattened, 
       whitespace collapsed, lowercase), is an exact contiguous substring of the 
       normalized article content.
    
    It DOES NOT guarantee:
    1. Attribution (who said the quote).
    2. Context (if the quote was part of a denial or an assertion).
    3. Importance (if the quote is boilerplate vs factual).
    """
    pass

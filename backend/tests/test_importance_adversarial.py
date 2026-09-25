import pytest
from app.core.importance import infer_event_signals, calibrate_importance_score

def test_importance_sensational_trivial():
    # An article with sensational words but no actual significant signals
    title = "You won't believe this INSANE new update to our terms of service!"
    content = "We have updated our terms of service. It is mind blowing!"
    kind, scope, security = infer_event_signals(title, None, content)
    
    assert kind == "other"
    assert scope == "product"
    
    # Even if the LLM gets hyped and gives it 90, calibration should crush it
    calibrated = calibrate_importance_score(90, kind, scope, security)
    assert calibrated <= 65 # "other" "product" ceiling is 65

def test_importance_quiet_security():
    # An article that is very dry but contains a critical CVE/RCE
    title = "Patch notes 1.4.2"
    content = "Fixes a remote code execution vulnerability in the core infrastructure module."
    kind, scope, security = infer_event_signals(title, None, content)
    
    assert security == "significant"
    assert kind == "security_incident"
    
    # If the LLM misses it and gives 40 (Minor), calibration should boost it!
    calibrated = calibrate_importance_score(40, kind, scope, security)
    assert calibrated >= 70 # "security_incident" "platform/product" floor is 70

def test_importance_famous_company_trivial_change():
    # A famous company making a tiny change (e.g. Google changed a button color)
    title = "Google changed the color of the search button"
    content = "The button is now slightly more blue. This is a monumental shift."
    kind, scope, security = infer_event_signals(title, None, content)
    
    # Signals won't see anything major
    assert kind == "other"
    
    # If LLM hallucinates importance 95 due to "Google", calibration clamps it
    calibrated = calibrate_importance_score(95, kind, scope, security)
    assert calibrated <= 65

def test_importance_unknown_company_significant_event():
    # Unknown startup releases a 100B open source model
    title = "RandomCorp releases 100B parameter open weights model"
    content = "We are releasing our 100B open weights checkpoint today."
    kind, scope, security = infer_event_signals(title, None, content)
    
    assert kind == "model_release"
    assert scope == "platform" # 100B open weights is platform scale
    
    # If LLM gives 40 because it doesn't recognize RandomCorp, calibration boosts it
    calibrated = calibrate_importance_score(40, kind, scope, security)
    assert calibrated >= 70

def test_importance_security_keyword_in_harmless_research():
    """
    Mentions "vulnerability" but is just research about vulnerability
    trends in aggregate, not an active incident.

    This was previously a documented KNOWN LIMITATION: infer_event_signals
    flagged bare "vulnerabilit\\w+" as security="significant" regardless
    of context, which pipeline.py's calibration override could then use
    to overrule an LLM that correctly said security="none" for a benign
    paper — a real, end-to-end exploitable false positive, not just an
    inaccurate helper function. Fixed via _VULN_RESEARCH_SURVEY_RE in
    app/core/importance.py (see docs/security-findings.md
    IMPORTANCE-RESEARCH-01 and
    tests/test_importance_research_vs_incident.py for the end-to-end
    pipeline reproduction/regression test). This test now asserts the
    corrected behavior instead of documenting the bug as permanent.
    """
    title = "A survey of vulnerability trends in 2024"
    content = "This research paper analyzes how vulnerabilities have changed."
    kind, scope, security = infer_event_signals(title, None, content)

    assert security == "none"
    assert kind != "security_incident"


def test_importance_genuine_incident_still_detected_alongside_survey_fix():
    """
    Neighboring attack on the IMPORTANCE-RESEARCH-01 fix: the survey/study
    exclusion must not swallow a genuine active incident that happens to
    be reported alongside research-sounding framing (e.g. a researcher
    who discovered and is disclosing a real, specific vulnerability).
    """
    title = "Researcher discloses critical RCE vulnerability in widely used library"
    content = (
        "A security researcher today disclosed a remote code execution vulnerability "
        "actively exploited in the wild, affecting a widely used open-source library. "
        "A patch is available and users should update immediately."
    )
    kind, scope, security = infer_event_signals(title, None, content)

    assert security == "significant", (
        "A genuine, specific, actively-exploited RCE disclosure must still be flagged "
        "significant — the survey/study exclusion must be narrow, not swallow real incidents."
    )
    assert kind == "security_incident"

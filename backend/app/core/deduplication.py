import hashlib
import re
from typing import Optional
from app.core.urls import sanitize_http_url
from app.core.presentation import strip_wrapping_quotes

def generate_content_hash(text: str) -> str:
    """Generate SHA256 hash for raw content to detect exact matches."""
    if not text:
        return ""
    # Normalize whitespace before hashing
    normalized_text = " ".join(text.split())
    return hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()


def normalize_url(url: str) -> str:
    """
    Canonical article URL for deduplication.

    Delegates to sanitize_http_url: http(s) only, no credentials, no
    javascript:/data:/file:, no literal private/loopback hosts.
    Query strings and fragments are stripped so tracking params do not
    create duplicate articles.
    """
    return sanitize_http_url(url, keep_query=False)


# Stop words used for Jaccard title similarity.
# Include domain-common terms that are near-universal in AI headlines but carry
# no discriminative meaning between events.
STOP_WORDS = {
    # Articles / conjunctions / prepositions
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "its", "it",
    # Frequent AI-domain filler — these appear in nearly every headline
    "ai", "new", "announces", "announced", "releases", "released", "launch",
    "launches", "launched", "introducing", "introduces", "update", "updates",
    "unveils", "unveil", "now", "latest",
}

def is_duplicate_title(title1: str, title2: str, threshold: float = 0.6) -> bool:
    """
    Deterministic string match for titles using Jaccard similarity.
    Lowercases, removes punctuation, ignores stop words.

    Does NOT by itself prove two articles are the same event. Callers that
    would merge on this signal MUST also check titles_suggest_different_events.
    """
    if not title1 or not title2:
        return False

    def normalize(t):
        t = t.lower()
        t = re.sub(r'[^\w\s]', '', t)
        words = set(t.split())
        return words - STOP_WORDS

    set1 = normalize(title1)
    set2 = normalize(title2)

    if not set1 or not set2:
        return False

    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))

    if union == 0:
        return False

    jaccard = intersection / union
    return jaccard >= threshold


# Distinctive markers that, when they differ between two titles, indicate
# different real-world events even if the rest of the headline is similar.
_SCALE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(billion|million|thousand|trillion|b|m|k)\b",
    re.IGNORECASE,
)
_PRODUCT_CODE_RE = re.compile(r"\b[a-z]{1,4}\d+[a-z0-9.\-]*\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_MONEY_UNIT_NORMALIZE = {
    "billion": "b", "b": "b",
    "million": "m", "m": "m",
    "thousand": "k", "k": "k",
    "trillion": "t",
}


_CODE_SEPARATOR_RE = re.compile(r"\b([a-z]{1,4})[-\s](\d+)")


def extract_event_markers(title: str) -> set[str]:
    """
    Extract distinctive factual markers from a headline: magnitudes
    ($6.6 billion), product codes (H200, GPT-5, B200), and remaining numbers.

    Used to prevent Jaccard title-matching from merging unrelated events
    that share company/verb structure.
    """
    if not title:
        return set()
    t = title.lower()
    markers: set[str] = set()

    for amount, unit in _SCALE_RE.findall(t):
        markers.add(f"scale:{amount}:{_MONEY_UNIT_NORMALIZE.get(unit.lower(), unit.lower())}")

    for code in _PRODUCT_CODE_RE.findall(t):
        markers.add(f"code:{code.lower().rstrip('.')}")

    # A short letter-prefix code written with a hyphen or space ("GPT-5",
    # "GPT 5") must extract to the same code marker as the fused spelling
    # ("GPT5") — otherwise the same product, written with different
    # punctuation across two outlets, registers as a marker conflict
    # (disjoint "num:5" vs "code:gpt5") and titles_suggest_different_events
    # wrongly reports two DIFFERENT events as conflicting. Reproduced
    # directly before this fix: extract_event_markers("GPT-5 released")
    # returned {"num:5"} while extract_event_markers("GPT5 released")
    # returned {"code:gpt5"} — disjoint sets, so the marker-conflict check
    # flagged them as different events. See docs/RED_TEAM_REPORT.md.
    # Added alongside the existing markers (not instead of) so the
    # unseparated form's own extraction (H200, B200, ...) is untouched.
    for prefix, digits in _CODE_SEPARATOR_RE.findall(t):
        markers.add(f"code:{prefix}{digits}")

    # Remaining standalone numbers (versions, counts) not already in a scale marker
    scaled_amounts = {m.split(":")[1] for m in markers if m.startswith("scale:")}
    for num in _NUMBER_RE.findall(t):
        if num not in scaled_amounts:
            markers.add(f"num:{num}")

    return markers


def titles_suggest_different_events(title1: str, title2: str) -> bool:
    """
    True when two similar headlines contain conflicting distinctive markers
    and therefore must NOT be merged on lexical similarity alone.

    Subset markers (e.g. "GPT-5" vs "GPT-5 API") do not conflict.
    Disjoint markers (e.g. "H200" vs "B200", "$6.6 billion" vs "$6.6 million")
    do conflict.
    """
    m1 = extract_event_markers(title1)
    m2 = extract_event_markers(title2)
    if not m1 or not m2:
        return False
    if m1 <= m2 or m2 <= m1:
        return False
    return True


# Curated, bounded antonym/contrast phrase groups — not exhaustive sentiment
# analysis, just the specific "same subject, opposite claim" pattern that
# defeats numeric-marker conflict detection: both titles can share the exact
# same product code/magnitude while asserting opposite facts about it
# ("H200 production on track" vs "H200 production behind").
_CONTRAST_GROUPS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (frozenset({"confirms", "confirmed", "confirm", "approves", "approved"}),
     frozenset({"denies", "denied", "deny", "rejects", "rejected", "blocks", "blocked"})),
    (frozenset({"passed", "pass", "passes"}),
     frozenset({"failed", "fails", "failing", "fail"})),
    (frozenset({"launches", "launched", "launch", "ships", "shipped"}),
     frozenset({"delays", "delayed", "delay", "postpones", "postponed", "cancels",
                "cancelled", "canceled", "scraps", "scrapped", "halts", "halted",
                "pauses", "paused"})),
    (frozenset({"increases", "increased", "increase", "rises", "rose", "grows", "grew"}),
     frozenset({"decreases", "decreased", "decrease", "falls", "fell", "drops",
                "dropped", "declines", "declined"})),
    (frozenset({"on track", "ahead of schedule", "on schedule"}),
     frozenset({"behind", "behind schedule", "off track"})),
    (frozenset({"beats", "beat", "exceeds", "exceeded"}),
     frozenset({"misses", "missed", "falls short"})),
    (frozenset({"wins", "won"}), frozenset({"loses", "lost"})),
    (frozenset({"hires", "hiring", "expands", "expanded"}),
     frozenset({"layoffs", "fires", "fired", "cuts", "shrinks", "shrank"})),
    (frozenset({"live", "restored", "back online", "back up"}),
     frozenset({"down", "outage", "offline"})),
)

_NEGATION_WORDS_RE = re.compile(
    r"\b(not|no|never|isn't|isnt|doesn't|doesnt|won't|wont|cannot|can't|cant|n't|denies|denied)\b",
    re.IGNORECASE,
)


def titles_have_contrasting_claims(title1: str, title2: str) -> bool:
    """
    True when two titles assert opposite facts about what is otherwise the
    same subject — the specific gap numeric/code markers cannot see, since
    "H200 production on track" and "H200 production behind" share the exact
    same code marker while contradicting each other. Two independent,
    directly reproduced signals (docs/RED_TEAM_REPORT.md
    DEDUP-CONTRADICTION-01):

    - a curated antonym/contrast phrase pair present one-per-title
    - a negation word ("not", "never", ...) present in only one title,
      with the rest of the wording otherwise close enough to have already
      passed the Jaccard threshold
    """
    t1 = (title1 or "").lower()
    t2 = (title2 or "").lower()
    if not t1 or not t2:
        return False

    for group_a, group_b in _CONTRAST_GROUPS:
        a_in_1 = any(term in t1 for term in group_a)
        b_in_1 = any(term in t1 for term in group_b)
        a_in_2 = any(term in t2 for term in group_a)
        b_in_2 = any(term in t2 for term in group_b)
        if (a_in_1 and b_in_2) or (b_in_1 and a_in_2):
            return True

    neg1 = bool(_NEGATION_WORDS_RE.search(t1))
    neg2 = bool(_NEGATION_WORDS_RE.search(t2))
    if neg1 != neg2:
        return True

    return False


def titles_are_safe_lexical_match(title1: str, title2: str, threshold: float = 0.85) -> bool:
    """
    True only when a Jaccard title match is safe to treat as the same event
    WITHOUT an LLM check.

    Requires:
    - high lexical overlap
    - no conflicting markers (H200 vs B200, $6.6B vs $6.6M)
    - no contrasting claims about the same subject (approved vs blocked,
      negation asymmetry) — see titles_have_contrasting_claims
    - at least one shared distinctive marker (model/code/magnitude)

    Generic headlines ("OpenAI Announces Update") must not fast-path merge.
    """
    if not is_duplicate_title(title1, title2, threshold=threshold):
        return False
    if titles_suggest_different_events(title1, title2):
        return False
    if titles_have_contrasting_claims(title1, title2):
        return False
    m1 = extract_event_markers(title1)
    m2 = extract_event_markers(title2)
    if not m1 or not m2:
        return False
    return bool(m1 & m2)


_MIN_CITATION_LENGTH = 15  # characters — shorter citations are meaninglessly broad

_UNICODE_PUNCT = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u00a0": " ",
    "\u202f": " ",
    "\ufeff": "",
})


def first_factual_line(text: Optional[str]) -> str:
    """First non-empty bullet/line from model output. Empty if nothing usable exists."""
    if not text:
        return ""
    for line in str(text).splitlines():
        cleaned = line.strip().lstrip("-•* ").strip()
        if cleaned:
            return cleaned
    return str(text).strip()


_CHROME_RE = re.compile(
    r"you must be signed in|notifications fork|sign in to change|"
    r"^back to articles\b|^upvote\b",
    re.I,
)


def first_source_excerpt(content: Optional[str], max_len: int = 420) -> str:
    """
    Last-resort summary from the article itself when the LLM left short_summary empty.

    Returns a contiguous source paragraph, not a generated paraphrase.
    Returns empty when the body is UI chrome or otherwise unusable.
    """
    import html

    if not content:
        return ""
    text = html.unescape(str(content))
    text = re.sub(r"<[^>]+>", " ", text)
    for chunk in re.split(r"\n+", text):
        cleaned = " ".join(chunk.split())
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
        usable = []
        for sentence in sentences:
            if re.match(r"^Editor['’]s note:", sentence, re.I):
                continue
            if re.match(r"^All references to the name have been updated", sentence, re.I):
                continue
            usable.append(sentence)
        cleaned = " ".join(usable).strip()
        if len(cleaned) < 80:
            continue
        if _CHROME_RE.search(cleaned):
            continue
        if max_len and len(cleaned) > max_len:
            clipped = cleaned[:max_len]
            for end in (". ", "? ", "! "):
                idx = clipped.rfind(end)
                if idx >= 80:
                    return clipped[: idx + 1].strip()
            return clipped.rsplit(" ", 1)[0].strip()
        return cleaned
    return ""


def _normalize_citation_text(text: str) -> str:
    """
    Compare citations against source text without changing the provenance rule:
    the citation must still appear as a contiguous substring of the article.
    """
    import html

    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = cleaned.translate(_UNICODE_PUNCT)
    cleaned = cleaned.replace("`", "'")
    cleaned = " ".join(cleaned.lower().split())
    return cleaned.strip(" \"'")


def verify_citations(article_content: str, citations: list[str]) -> list[str]:
    """
    Deterministically verifies that LLM-generated citations actually exist in the source text.

    Rejects:
    - Citations shorter than _MIN_CITATION_LENGTH characters (e.g. "AI", "model")
      which would trivially match any article and provide no evidence value.
    - Citations whose normalized text is not an exact substring of the normalized article.

    Returns only citations that pass both checks.
    """
    if not citations or not article_content:
        return []

    verified = []
    normalized_content = _normalize_citation_text(article_content)

    for citation in citations:
        if isinstance(citation, dict):
            citation = (
                citation.get("text")
                or citation.get("quote")
                or citation.get("citation")
                or citation.get("span")
            )
        if not isinstance(citation, str):
            continue
        if len(citation.strip()) < _MIN_CITATION_LENGTH:
            continue

        normalized_citation = _normalize_citation_text(citation)
        if len(normalized_citation) < _MIN_CITATION_LENGTH:
            continue

        if normalized_citation in normalized_content:
            verified.append(strip_wrapping_quotes(citation))

    return verified


_STOP = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "its", "it",
    "this", "that", "as", "be", "been",
}


def _content_sentences(article_content: str) -> list[str]:
    import html

    text = html.unescape(str(article_content or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out = []
    for sentence in sentences:
        if len(sentence.split()) < 12:
            continue
        if re.search(
            r"why it matters|group fields|you must be signed|reference tables|tokens/task|test_normal",
            sentence,
            re.I,
        ):
            continue
        if re.match(r"^\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", sentence):
            continue
        if not re.search(
            r"\b(the|a|an|to|for|with|that|from|was|were|has|have|this|their|into|over)\b",
            sentence,
            re.I,
        ):
            continue
        # Noun-pile / heading lists (Exploit chain libheif Image decoder …)
        caps = re.findall(r"\b[A-Z][A-Za-z0-9.+-]*\b", sentence)
        if len(caps) >= 8 and not re.search(r"\b[a-z]{3,}ed\b", sentence):
            continue
        if len(sentence) > 280:
            sentence = sentence[:280].rsplit(" ", 1)[0].strip()
        out.append(sentence)
    return out


def _token_set(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def fallback_source_citations(
    article_content: str,
    *,
    short_summary: Optional[str] = None,
    what_changed: Optional[str] = None,
    existing: Optional[list] = None,
    limit: int = 2,
) -> list[str]:
    """
    When the LLM produced no verifiable quotes, copy 1-2 source sentences
    that overlap the grounded summary. Never paraphrases. Still runs through
    verify_citations.
    """
    verified = list(existing or [])
    if verified or not article_content:
        return verified
    claim = " ".join(part for part in (short_summary, what_changed) if part)
    claim_tokens = _token_set(claim)
    if len(claim_tokens) < 3:
        return []

    scored: list[tuple[int, str]] = []
    for sentence in _content_sentences(article_content):
        overlap = len(claim_tokens & _token_set(sentence))
        if overlap < 3:
            continue
        scored.append((overlap, sentence))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    candidates = [sentence for _, sentence in scored[: max(limit, 1) * 3]]
    return verify_citations(article_content, candidates)[:limit]

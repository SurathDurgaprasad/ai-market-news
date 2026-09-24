import hashlib
import re
from typing import Optional
from urllib.parse import urlparse
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


def content_tokens(title: str) -> set[str]:
    """Lowercased headline words with stop words and punctuation removed."""
    if not title:
        return set()
    text = title.lower().replace("-", " ")
    text = re.sub(r"[^\w\s]", "", text)
    return {word for word in text.split() if word and word not in STOP_WORDS}


def titles_are_safe_lexical_match(title1: str, title2: str, threshold: float = 0.85) -> bool:
    """
    True only when a Jaccard title match is safe to treat as the same event
    WITHOUT an LLM check.

    Requires:
    - high lexical overlap
    - no conflicting markers (H200 vs B200, $6.6B vs $6.6M)
    - no contrasting claims about the same subject (approved vs blocked,
      negation asymmetry) — see titles_have_contrasting_claims
    - either a shared distinctive marker (model/code/magnitude) OR a long
      shared content-word overlap (the same investigation headline republished
      with no product code). Generic headlines ("OpenAI Announces Update")
      have too few content words and must not fast-path merge.
    """
    if not is_duplicate_title(title1, title2, threshold=threshold):
        return False
    if titles_suggest_different_events(title1, title2):
        return False
    if titles_have_contrasting_claims(title1, title2):
        return False
    m1 = extract_event_markers(title1)
    m2 = extract_event_markers(title2)
    if m1 and m2 and (m1 & m2):
        return True
    return len(content_tokens(title1) & content_tokens(title2)) >= 5


_RELEASE_LEAD = re.compile(
    r"^(?:the\s+)?(?:introduction|release|launch|announcement)\s+of\s+",
    re.IGNORECASE,
)
_RELEASE_GENERIC = {"model", "models", "llm", "llms", "ai"}


def _release_core(title: str) -> Optional[list[str]]:
    """
    Content words of a release-style headline, or None if the title is not
    phrased as 'Introduction/Release/Launch/Announcement of ...'.
    """
    raw = (title or "").strip()
    if not raw or not _RELEASE_LEAD.match(raw):
        return None
    rest = _RELEASE_LEAD.sub("", raw).lower()
    rest = re.sub(r"[^\w\s.]", " ", rest)
    words: list[str] = []
    for word in rest.split():
        word = word.strip(".")
        if not word or word in STOP_WORDS or word in _RELEASE_GENERIC:
            continue
        words.append(word)
    if len(words) < 3:
        return None
    return words


def titles_are_same_release_wording(title1: str, title2: str) -> bool:
    """
    Same named release written as 'Release of X' vs 'Introduction of X model'.

    Both titles must use that lead-in. A later availability note
    ('now available on Bedrock') and a program that uses the model do not match.
    """
    left = _release_core(title1)
    right = _release_core(title2)
    if not left or not right:
        return False
    if titles_suggest_different_events(title1, title2):
        return False
    if titles_have_contrasting_claims(title1, title2):
        return False
    shared = set(left) & set(right)
    union = set(left) | set(right)
    if not union:
        return False
    return len(shared) / len(union) >= 0.8


_DISTRIBUTION_PHRASE = re.compile(
    r"\b(available on|now available|released on)\b",
    re.IGNORECASE,
)
_YEAR_TOKEN = re.compile(r"^(19|20)\d{2}$")


def _normalized_content_words(title: str) -> list[str]:
    text = (title or "").lower()
    text = re.sub(r"u\.s\.?", "us ", text)
    text = text.replace("-", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text)
    words = []
    for word in text.split():
        if not word or word in STOP_WORDS or _YEAR_TOKEN.match(word):
            continue
        words.append(word)
    return words


def _content_ngrams(words: list[str], size: int) -> set[str]:
    if len(words) < size:
        return set()
    return {" ".join(words[index : index + size]) for index in range(len(words) - size + 1)}


_ANNOUNCEMENT_ACT = re.compile(
    r"\b(launches|launch of|releases|release of|introduces|introduction of|unveils)\b",
    re.IGNORECASE,
)
_DEPLOYMENT_ACT = re.compile(
    r"\b(migration|migrates|implements|implementation|deploys|deployed|integrates)\b",
    re.IGNORECASE,
)
_TEMPLATE_VERBS = {
    "utilizes", "utilize", "enhances", "enhance", "launches", "launch",
    "introduces", "introduce", "becomes", "become", "achieves", "achieve",
    "integrates", "integrate", "implements", "implement", "releases",
    "announces", "announce", "develops", "develop", "offers", "offer",
    "updates", "update",
}
_GENERIC_OVERLAP = {
    "research", "features", "feature", "model", "models", "data",
    "system", "systems", "platform", "update", "updates", "release",
}


def _specific_shared_story(title1: str, title2: str) -> bool:
    """
    True when two headlines share one incident phrase, not a product template.

    A swapped name on an otherwise identical headline stays apart. A shared
    model number, or a verb such as 'launches' or 'utilizes', is not the event.
    """
    announced = bool(_ANNOUNCEMENT_ACT.search(title1 or ""))
    deployed = bool(_DEPLOYMENT_ACT.search(title1 or ""))
    other_announced = bool(_ANNOUNCEMENT_ACT.search(title2 or ""))
    other_deployed = bool(_DEPLOYMENT_ACT.search(title2 or ""))
    if (announced and not deployed and other_deployed and not other_announced) or (
        other_announced and not other_deployed and deployed and not announced
    ):
        return False
    words1 = _normalized_content_words(title1)
    words2 = _normalized_content_words(title2)
    shared = set(words1) & set(words2)
    if len(shared) < 4:
        return False
    only_left = set(words1) - shared
    only_right = set(words2) - shared
    if (
        len(only_left) == 1
        and len(only_right) == 1
        and words1
        and words2
        and words1[0] in only_left
        and words2[0] in only_right
    ):
        return False
    grams = (_content_ngrams(words1, 4) & _content_ngrams(words2, 4)) or (
        _content_ngrams(words1, 3) & _content_ngrams(words2, 3)
    )
    usable = []
    for gram in grams:
        tokens = gram.split()
        if any(token.isdigit() for token in tokens):
            continue
        if any(token in _TEMPLATE_VERBS for token in tokens):
            continue
        usable.append(tokens)
    if not usable:
        return False
    covered = {token for tokens in usable for token in tokens}
    return any(
        token not in _GENERIC_OVERLAP and len(token) >= 5
        for token in shared - covered
    )


def classify_headline_relationship(
    title1: str,
    title2: str,
    kind1: str = "",
    kind2: str = "",
) -> str:
    """
    Deterministic relationship for two headlines.

    SAME_EVENT is one underlying development told with different punctuation,
    framing, or wording. UPDATE_TO_SAME_EVENT is a later distribution of a
    release. DIFFERENT_EVENT covers a new incident, a separate investigation,
    a research note versus a product release, and a security incident versus
    a launch. Marker conflicts and contrasting claims stay in force.
    """
    from app.core.providers.llm import EventRelationship

    if titles_suggest_different_events(title1, title2):
        return EventRelationship.DIFFERENT_EVENT
    if titles_have_contrasting_claims(title1, title2):
        return EventRelationship.DIFFERENT_EVENT

    kinds = {(kind1 or "").strip().lower(), (kind2 or "").strip().lower()}
    kinds.discard("")
    incompatible = {
        frozenset({"security_incident", "model_release"}),
        frozenset({"security_incident", "model_family"}),
        frozenset({"security_incident", "hardware_platform"}),
        frozenset({"security_incident", "research"}),
        frozenset({"research", "model_release"}),
        frozenset({"research", "model_family"}),
        frozenset({"research", "hardware_platform"}),
    }
    split_kinds = kinds in incompatible

    distributed = _DISTRIBUTION_PHRASE.search(title1 or "")
    other_distributed = _DISTRIBUTION_PHRASE.search(title2 or "")
    if bool(distributed) != bool(other_distributed):
        left = set(_normalized_content_words(title1))
        right = set(_normalized_content_words(title2))
        if len(left & right) >= 3:
            return EventRelationship.UPDATE_TO_SAME_EVENT

    if titles_are_safe_lexical_match(title1, title2) or titles_are_same_release_wording(title1, title2):
        if split_kinds:
            return EventRelationship.DIFFERENT_EVENT
        return EventRelationship.SAME_EVENT

    if split_kinds:
        return EventRelationship.DIFFERENT_EVENT

    if _specific_shared_story(title1, title2):
        return EventRelationship.SAME_EVENT
    return EventRelationship.DIFFERENT_EVENT


def titles_are_same_outlet_paraphrase(title1: str, title2: str) -> bool:
    """
    Same outlet restating one story ('Failures of US Border Surveillance' vs
    'Failures in US-Mexico Border Surveillance').

    Callers must already know the articles share a source. High overlap of
    specific words is required so two different posts from one blog do not merge.
    """
    if titles_suggest_different_events(title1, title2):
        return False
    if titles_have_contrasting_claims(title1, title2):
        return False
    left = content_tokens(title1)
    right = content_tokens(title2)
    if len(left) < 5 or len(right) < 5:
        return False
    shared = left & right
    union = left | right
    if len(shared) < 5 or not union:
        return False
    if len(shared) / len(union) < 0.5:
        return False
    # A swapped subject ("Baseten" vs "DeepInfra" on the same headline template)
    # puts a unique token on both sides. A republished story only adds modifiers.
    only_left = left - right
    only_right = right - left
    if only_left and only_right:
        return False
    return len(only_left or only_right) <= 2


# A later distribution, benchmark, price change, or deployment of a named
# product is a different event from the announcement itself.
_DISTINCT_COVERAGE = re.compile(
    r"\b("
    r"available on|now available|released on|comes to|lands on|"
    r"benchmarks?|raises|funding|acquires|acquisition|"
    r"implements|deploys|integrates|enhances|built with|\buses\b|"
    r"pric(?:e|ing)"
    r")\b",
    re.IGNORECASE,
)

_ANNOUNCEMENT = re.compile(
    r"\b("
    r"introduction of|release of|launch of|announcement of|"
    r"announces|launches|releases|unveils|introduces"
    r")\b",
    re.IGNORECASE,
)

_TITLE_NAMED_PRODUCT = re.compile(
    r"\b("
    r"claude(?:\s+[a-z]+){0,3}\s+\d+\.\d+(?:\.\d+)?|"
    r"gpt-\d+(?:\.\d+)?\s+(?:sol|luna|turbo|mini|pro|nano)"
    r")\b",
    re.IGNORECASE,
)

_URL_NAMED_PRODUCT = re.compile(
    r"(?:"
    r"claude(?:-[a-z]+){0,3}-\d+-\d+|"
    r"opus-\d+-\d+|"
    r"gpt-\d+(?:-\d+)?-(?:sol|luna|turbo|mini|pro|nano)"
    r")",
    re.IGNORECASE,
)


def _normalize_product_key(raw: str) -> str:
    text = raw.lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9.\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\b(\d+)\s+(\d+)\b", r"\1.\2", text)


def named_product_keys(title: Optional[str] = None, url: Optional[str] = None) -> set[str]:
    """Versioned or code-named products actually written in a title or stored URL."""
    keys: set[str] = set()
    if title:
        for match in _TITLE_NAMED_PRODUCT.findall(title):
            key = _normalize_product_key(match)
            if key:
                keys.add(key)
    if url:
        path = urlparse(url).path if "://" in url else url
        for match in _URL_NAMED_PRODUCT.findall(path):
            key = _normalize_product_key(match)
            if key:
                keys.add(key)
    return keys


def _product_keys_overlap(left: set[str], right: set[str]) -> bool:
    for a in left:
        for b in right:
            if a == b or a.endswith(" " + b) or b.endswith(" " + a):
                return True
    return False


def coverage_of_same_named_release(
    title1: str,
    url1: Optional[str],
    title2: str,
    url2: Optional[str],
) -> bool:
    """
    True when one stored article is coverage of the same named release as the other.

    The product name has to appear in a headline or in a URL the pipeline
    already stored. Availability notes, benchmarks, pricing, and deployments
    of that product stay separate.
    """
    if titles_suggest_different_events(title1, title2):
        return False
    if titles_have_contrasting_claims(title1, title2):
        return False
    if _DISTINCT_COVERAGE.search(title1 or "") or _DISTINCT_COVERAGE.search(title2 or ""):
        return False
    titled = (named_product_keys(title1), named_product_keys(title2))
    # Both headlines already name a product. A later use, service tier, or
    # deployment of that product must not collapse into the launch card.
    # This path is only for a generic coverage headline whose stored URL
    # carries the product name.
    if titled[0] and titled[1]:
        return False
    if not titled[0] and not titled[1]:
        return False
    if not (_ANNOUNCEMENT.search(title1 or "") and _ANNOUNCEMENT.search(title2 or "")):
        return False
    return _product_keys_overlap(named_product_keys(title1, url1), named_product_keys(title2, url2))


_VERSIONED_NAME = re.compile(
    r"\b([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,4}\s+\d+(?:\.\d+)+)\b"
)


def title_versioned_entities(title: str) -> list[str]:
    """
    Product names with a version in the headline ('Claude Opus 5.5').

    Used only when the classifier returned no entities, so a second article
    about the same named release can still reach relationship classification.
    """
    if not title:
        return []
    found: list[str] = []
    for match in _VERSIONED_NAME.findall(title):
        name = re.sub(r"\s+", " ", match).strip()
        if name and name not in found:
            found.append(name)
    return found[:4]


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


# ── Evidence integrity ────────────────────────────────────────────────────
#
# A quote being present in the fetched text is necessary, not sufficient.
# Page text is untrusted: it can contain a note addressed to the model
# ("make sure the citations array contains 'X'"), and X is then trivially a
# substring of the source. Evidence must also (a) not come from text that
# addresses the model, and (b) share content with the claim it supports.
# Both checks are deterministic and never ask the LLM about its own output.

_INSTRUCTION_CONTEXT = re.compile(
    r"\b("
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)|"
    r"disregard (?:all |any |the )?(?:previous|prior|above|earlier)|"
    r"(?:ignore|reveal|override|disregard|print) (?:the |your )?system prompt|"
    r"developer note|note to (?:the )?(?:ai|model|assistant|llm|summari[sz]er|reader model)|"
    # Addressed to the reader-model and about what to produce. "You must be
    # signed in" and "the model must be fine-tuned" are ordinary page text.
    r"(?:you|the (?:ai|assistant|llm|summari[sz]er)) (?:must|should|are required to|have to|will now) "
    r"(?:always )?(?:output|return|include|cite|quote|set|respond|write|say|report|rate|score|classify|"
    r"ignore|state|mention|add)|"
    r"please (?:ensure|make sure|include|output|set|quote|add|respond|return|cite)|"
    r"citations? (?:array|field|list|must|should)|"
    r"importance[_ ]score|security_impact|event_kind|"
    r"(?:output|return|respond with) (?:an? |the )?(?:json|score|string|citation|value)|"
    r"even though it does not appear|as an ai language model"
    r")\b",
    re.IGNORECASE,
)

def is_instruction_context(text: Optional[str]) -> bool:
    """True when text addresses the model rather than stating the article's facts."""
    return bool(_INSTRUCTION_CONTEXT.search(text or ""))


def _claim_stems(text: Optional[str]) -> set[str]:
    """Content stems for claim support. Version and number tokens are kept whole."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", (text or "").lower()):
        if word in _EVIDENCE_STOPWORDS:
            continue
        if any(ch.isdigit() for ch in word):
            out.add(word)
        elif len(word) >= 3:
            out.add(word[:5])
    return out


def claim_stems(text: Optional[str]) -> set[str]:
    """Public: content stems, numbers and version tokens of a text."""
    return _claim_stems(text)


def citation_supports_claim(citation: Optional[str], claim: Optional[str]) -> bool:
    """A quote supports a claim only when they share at least one content stem."""
    return bool(_claim_stems(citation) & _claim_stems(claim))


_NON_CONTENT = re.compile(
    r"<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>|<!--.*?-->",
    re.IGNORECASE | re.DOTALL,
)


def _readable_source(article_content: str) -> str:
    """Source text a reader sees: script, style and comment contents removed."""
    return _NON_CONTENT.sub(" ", article_content or "")


def _sentence_start(text: str, before: int) -> int:
    left = max(text.rfind(mark, 0, before) for mark in (". ", "! ", "? "))
    return 0 if left < 0 else left + 1


def _sentence_around(text: str, start: int, end: int) -> str:
    """
    The sentence containing [start, end) plus the sentence before it. An
    injected directive usually precedes its payload
    ("Ignore previous instructions. <payload>").
    """
    left = _sentence_start(text, start)
    if left > 1:
        left = _sentence_start(text, left - 1)
    # Start at the quote's last character so a quote that ends with its own
    # period is not extended into the following sentence.
    rights = [text.find(mark, max(start, end - 1)) for mark in (". ", "! ", "? ")]
    rights = [r for r in rights if r >= 0]
    right = min(rights) + 1 if rights else len(text)
    return text[left:right]


def validate_evidence(
    article_content: str,
    citations: list,
    *,
    claim: Optional[str],
) -> list[str]:
    """
    Evidence that is (1) a contiguous span of the fetched source after
    normalization, (2) not taken from text addressed to the model, and
    (3) supports the claim (headline, summary, key changes). Duplicates
    are dropped. The LLM is never asked to judge its own citations.
    """
    readable = _readable_source(article_content)
    present = verify_citations(readable, citations)
    if not present:
        return []
    source = _normalize_citation_text(readable)
    kept: list[str] = []
    seen: set[str] = set()
    for quote in present:
        normalized = _normalize_citation_text(quote)
        if normalized in seen:
            continue
        index = source.find(normalized)
        if index < 0:
            continue
        context = _sentence_around(source, index, index + len(normalized))
        if is_instruction_context(context) or is_instruction_context(quote):
            continue
        if not citation_supports_claim(quote, claim):
            continue
        seen.add(normalized)
        kept.append(quote)
    return kept


_STOP = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "its", "it",
    "this", "that", "as", "be", "been",
}


_EVIDENCE_STOPWORDS = _STOP | {
    "will", "can", "has", "have", "not", "more", "than", "our", "your",
    "their", "they", "we", "you", "all", "any", "also", "into", "new",
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
        if is_instruction_context(sentence):
            continue
        overlap = len(claim_tokens & _token_set(sentence))
        if overlap < 3:
            continue
        scored.append((overlap, sentence))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    candidates = [sentence for _, sentence in scored[: max(limit, 1) * 3]]
    return validate_evidence(article_content, candidates, claim=claim)[:limit]


# Tokens that change on every fetch of an unchanged article: counters and
# relative times ("Upvote 72", "+66", "3 days ago", "followerCount": 4172).
# A number is volatile only in those exact shapes, so a corrected figure
# ("raised $300 million this week" -> "$350 million") stays material.
_COUNTER_WORDS = {
    "+", "upvote", "upvotes", "like", "likes", "view", "views", "comment", "comments",
    "reads", "stars", "followers", "replies", "reply",
}
_TIME_UNITS = {
    "second", "seconds", "minute", "minutes", "hour", "hours", "day", "days",
    "week", "weeks", "month", "months", "year", "years",
}
_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}
_VOLATILE_WORDS = _COUNTER_WORDS | _TIME_UNITS | {"a", "an", "ago", "just", "now", "yesterday"}
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*|[^\sa-z0-9]", re.IGNORECASE)
_NUMBER_TOKEN = re.compile(r"[0-9][0-9.,]*")


def _numbers_are_volatile(tokens: list, start: int, end: int) -> bool:
    """Whether the changed span tokens[start:end] is a counter or a relative time."""
    lower = [token.lower() for token in tokens]
    before = lower[start - 1] if start > 0 else ""
    after = lower[end] if end < len(lower) else ""
    if before in _COUNTER_WORDS or after in _COUNTER_WORDS:
        return True
    if any(word in _COUNTER_WORDS for word in lower[start:end]):
        return True  # the span is itself a counter, e.g. "Upvote 72"
    tail = lower[start:end] + lower[end:end + 2]
    if any(word in _TIME_UNITS and tail[index + 1:index + 2] == ["ago"] for index, word in enumerate(tail)):
        return True
    # Related-post cards: "<upvotes> <Month> <day>". Prose dates read
    # "August 17" or "17 August 2026", never a count before the month.
    if after in _MONTHS and end + 1 < len(lower) and re.fullmatch(r"[0-9]{1,2}", lower[end + 1]):
        return True
    return any(word.endswith("count") for word in lower[max(0, start - 3):start])


def _is_boundary_token(token: str) -> bool:
    """Punctuation that appears when surrounding text is removed."""
    return not any(ch.isalnum() for ch in token)


def is_immaterial_change(old_content: Optional[str], new_content: Optional[str]) -> bool:
    """
    True when two versions of one article differ only in counters and
    relative times. Any other changed word or figure (a correction, an added
    update paragraph) is material and keeps the versioned-update behavior.
    """
    import difflib
    import unicodedata

    if not old_content or not new_content:
        return False
    # NFKC: a full-width "＞" in one fetch and ">" in the next is one character.
    old_tokens = _TOKEN.findall(unicodedata.normalize("NFKC", old_content))
    new_tokens = _TOKEN.findall(unicodedata.normalize("NFKC", new_content))
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    from app.core.article_body import MAX_CONTENT_CHARS

    # Stored bodies are cut at MAX_CONTENT_CHARS. When either side hit the
    # cap, a difference touching the end is where the cut fell, not an edit.
    truncated = max(len(old_content), len(new_content)) >= MAX_CONTENT_CHARS - 1
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if truncated and (i2 == len(old_tokens) or j2 == len(new_tokens)):
            continue
        if tag in ("equal", "delete"):
            # Text only removed (page chrome, comments, embedded data that a
            # cleaner extraction no longer includes) carries no new fact.
            continue
        if tag == "replace":
            removed = {token.lower() for token in old_tokens[i1:i2]}
            if all(token.lower() in removed or _is_boundary_token(token) for token in new_tokens[j1:j2]):
                continue  # a shorter or reordered remnant of what was there
        changed = old_tokens[i1:i2] + new_tokens[j1:j2]
        words = [token for token in changed if not _NUMBER_TOKEN.fullmatch(token)]
        if not all(token.lower() in _VOLATILE_WORDS for token in words):
            return False
        if len(words) == len(changed):
            continue
        sides = [(old_tokens, i1, i2), (new_tokens, j1, j2)]
        if not all(_numbers_are_volatile(seq, a, b) for seq, a, b in sides if b > a):
            return False
    return True

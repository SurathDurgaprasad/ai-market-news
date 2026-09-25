"""
Keep the organization in a generated headline.

The summarizer sometimes replaces the subject with a descriptor:
"Startup Raises $350 Million Series E Funding" when the publisher's own
title says "Snorkel AI triples valuation ...". This restores the name only
when it is confidently known, and otherwise leaves the headline alone.

Rules:
- Only a generic placeholder subject is replaced ("Startup", "AI company",
  "Researchers"). Any other headline is returned unchanged.
- The organization must lead the publisher's own title as one unambiguous
  name, doing the same kind of action as the headline (funding, launch,
  research, deal), and must not be the outlet. The body is often only a
  teaser, so it is not required to repeat the name.
- Nothing is guessed from a domain, a publisher, or a platform that hosts
  other people's work.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# A descriptor standing in for the actor. Singular nouns are replaced by the
# name ("Startup Raises" -> "Snorkel AI Raises"); people nouns keep the noun
# ("Researchers Develop" -> "MIT Researchers Develop") so the verb still agrees.
_SINGULAR = r"startup|company|firm|lab|unicorn|chipmaker|biotech|developer|maker|provider|vendor"
_PEOPLE = r"researchers|scientists|engineers"
_QUALIFIER = r"(?:(?:ai|artificial intelligence|tech|chip|robotics|software|data|defense|healthcare|fintech|[a-z]+-based)\s+)?"
# The placeholder must be the actor, i.e. directly followed by a verb.
# "Developer Tools Get an Upgrade" is not a placeholder subject.
_HEADLINE_VERB = (
    r"raises?|secures?|closes?|lands?|launch(?:es)?|releases?|unveils?|introduces?|announces?|"
    r"debuts?|ships?|develops?|builds?|creates?|trains?|publishes?|acquires?|buys?|opens?|"
    r"expands?|partners?|hires?|files?|reaches?|achieves?|reports?|claims?|wins?|triples|doubles|"
    r"valued|nabs?|bags?|gets?|unveil|show|shows|find|finds|propose|proposes|demonstrate|demonstrates"
)
_GENERIC_SUBJECT = re.compile(
    rf"^(?P<article>(?:an?|the)\s+)?(?P<qual>{_QUALIFIER})(?:(?P<one>{_SINGULAR})|(?P<people>{_PEOPLE}))"
    rf"(?=\s+(?P<verb>{_HEADLINE_VERB})\b)",
    re.IGNORECASE,
)

# The title's actor must be doing the same kind of thing as the headline's
# placeholder: "Snorkel AI triples valuation" and "Startup Raises $350M" are
# both funding. "Sequoia leads a round in X" is not X raising money.
_ACTION_FAMILIES = {
    "funding": {"raise", "raises", "secure", "secures", "close", "closes", "land", "lands", "nab", "nabs",
                "bag", "bags", "triples", "doubles", "valued", "valuation", "gets", "get"},
    "launch": {"launch", "launches", "release", "releases", "unveil", "unveils", "introduce", "introduces",
               "debut", "debuts", "ship", "ships", "announce", "announces", "open", "opens"},
    "research": {"develop", "develops", "build", "builds", "create", "creates", "train", "trains",
                 "publish", "publishes", "show", "shows", "find", "finds", "propose", "proposes",
                 "demonstrate", "demonstrates", "reveal", "reveals"},
    "deal": {"acquire", "acquires", "buy", "buys", "partner", "partners"},
}


def _family(verb: Optional[str]) -> Optional[str]:
    word = (verb or "").lower()
    for family, verbs in _ACTION_FAMILIES.items():
        if word in verbs:
            return family
    return None


_ADJECTIVE_LEAD = re.compile(r".+-(?:backed|based|owned|led|funded|focused|born|style)$", re.IGNORECASE)

# Where the actor ends in a publisher title ("Snorkel AI triples valuation").
_TITLE_VERBS = re.compile(
    r"^(?:raises?|triples|doubles|launch(?:es)?|releases?|unveils?|announces?|introduces?|secures?|"
    r"closes?|lands?|gets?|acquires?|buys?|partners?|debuts?|ships?|hires?|files?|sues?|says?|is|has|"
    r"wins?|hits?|reaches?|nabs?|bags?|opens?|expands?|builds?|trains?|publishes?|reveals?|"
    r"valued|valuation|reportedly|plans?|wants?|will|to|in|at|for|with|and|&|vs\.?|,)$",
    re.IGNORECASE,
)
_NOT_AN_ACTOR = re.compile(r"^(?:how|why|what|when|where|who|exclusive|breaking|report|the|a|an|this|these|inside)$", re.I)
_NAME_TOKEN = re.compile(r"^[A-Z0-9][\w.+\-]*$")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _contains(haystack: str, needle: str) -> bool:
    needle = _norm(needle)
    return bool(needle) and f" {needle} " in f" {_norm(haystack)} "


def _title_lead(title: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(actor, the word right after it) for a publisher title, or (None, None)."""
    words = (title or "").strip().split()
    if not words:
        return None, None
    first = words[0].strip("'\"‘’“”:")
    if not first or _NOT_AN_ACTOR.match(first):
        return None, None
    actor: list[str] = []
    for word in words:
        token = word.strip(",:;")
        possessive = token.endswith(("'s", "’s"))
        if possessive:
            token = token[:-2]
        if _TITLE_VERBS.match(token) or not _NAME_TOKEN.match(token):
            break
        if _ADJECTIVE_LEAD.match(token):
            return None, None  # "Nvidia-backed startup ..." does not name the actor
        actor.append(token)
        if possessive or word.endswith((",", ":", ";")) or len(actor) > 4:
            break
    if not actor or len(actor) > 4:
        return None, None
    following = words[len(actor)] if len(words) > len(actor) else ""
    following = following.strip(",:;").lower()
    # "OpenAI and Microsoft ..." has two actors: ambiguous, never pick one.
    if following in {"and", "&", "with", "vs", "vs."}:
        return None, None
    return " ".join(actor), following or None


def leading_actor(title: Optional[str]) -> Optional[str]:
    """
    The name a publisher title leads with, e.g. "Snorkel AI" from
    "Snorkel AI triples valuation to $3.5B". None when the title does not
    start with one clear name (questions, "X and Y", quotes, lowercase).
    """
    return _title_lead(title)[0]


def confident_organization(
    *,
    source_title: Optional[str],
    content: Optional[str] = None,
    entities: Iterable[str] = (),
    publisher_names: Iterable[str] = (),
    action: Optional[str] = None,
) -> Optional[str]:
    """
    The organization a generic headline refers to, or None.

    The publisher's own title must lead with one unambiguous name that is
    not the outlet, doing the same kind of action as the headline (action is
    the headline's verb). The title is the publisher's own attribution; the
    body is often only a teaser and is not required to repeat the name.
    """
    actor, title_verb = _title_lead(source_title)
    if not actor:
        return None
    if any(_contains(actor, name) or _contains(name, actor) for name in publisher_names if name):
        return None
    family = _family(action)
    if family is None or _family(title_verb) != family:
        return None
    for entity in entities or ():
        if isinstance(entity, str) and _norm(entity) == _norm(actor):
            return entity.strip()
    return actor


def restore_headline_organization(
    headline: str,
    *,
    source_title: Optional[str],
    content: Optional[str],
    entities: Iterable[str] = (),
    publisher_names: Iterable[str] = (),
) -> str:
    """Replace a generic placeholder subject with the confidently known organization."""
    text = (headline or "").strip()
    match = _GENERIC_SUBJECT.match(text)
    if not match:
        return headline
    organization = confident_organization(
        source_title=source_title,
        content=content,
        entities=entities,
        publisher_names=publisher_names,
        action=match.group("verb"),
    )
    if not organization or _contains(text, organization):
        return headline
    rest = text[match.end():]
    if match.group("people"):
        return f"{organization} {match.group('people')}{rest}"
    return f"{organization}{rest}"


def repair_stored_headlines(db, *, apply: bool = False) -> list[tuple[str, str]]:
    """
    Apply the same rule to live events already stored. Returns (old, new)
    pairs. With apply, the original headline is kept in
    importance_reasoning["original_headline"] so the change is reversible.
    """
    from app.models.article import Article
    from app.models.event import Event, EventArticle

    changes: list[tuple[str, str]] = []
    rows = (
        db.query(Event, Article)
        .join(EventArticle, EventArticle.event_id == Event.id)
        .join(Article, Article.id == EventArticle.article_id)
        .filter(Event.superseded_by_id.is_(None), EventArticle.link_type == "primary")
        .all()
    )
    for event, article in rows:
        if not _GENERIC_SUBJECT.match((event.headline or "").strip()):
            continue
        source = event.primary_source
        publishers = [event.official_source_name, article.publisher_name]
        if source is not None:
            publishers.append(source.name)
            if source.organization is not None:
                publishers.append(source.organization.name)
        restored = restore_headline_organization(
            event.headline,
            source_title=article.title,
            content=article.raw_content,
            entities=list(event.entities or []) + list(event.mentioned_entities or []),
            publisher_names=[name for name in publishers if name],
        )
        if restored == event.headline:
            continue
        changes.append((event.headline, restored))
        if apply:
            reasoning = dict(event.importance_reasoning) if isinstance(event.importance_reasoning, dict) else {}
            reasoning.setdefault("original_headline", event.headline)
            event.importance_reasoning = reasoning
            event.headline = restored
    if apply and changes:
        db.commit()
    return changes

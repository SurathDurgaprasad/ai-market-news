"""
Probe the seeded source registry.

Classifies each configured feed URL. Does not delete failing sources.

Usage (from backend/):
    python validate_source_registry.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from seed_sources import SOURCES
from app.core.fetcher import fetch_url
from app.core.parser import parse_rss_feed, extract_feed_next_url


def classify_response(url: str) -> dict:
    try:
        response = fetch_url(url, timeout=12)
    except Exception as exc:
        msg = str(exc)
        kind = "inaccessible"
        if "Unsafe URL" in msg:
            kind = "invalid"
        return {"url": url, "status": kind, "detail": msg[:200], "items": 0, "next": None}

    final = str(getattr(response, "url", "") or url)
    redirected = final.rstrip("/") != url.rstrip("/")
    articles = parse_rss_feed(response.text or "")
    nxt = extract_feed_next_url(response.text or "")
    status = "working" if articles else "changed"
    if redirected and articles:
        status = "redirected"
    if response.status_code >= 400:
        status = "inaccessible"
    return {
        "url": url,
        "status": status,
        "detail": f"http {response.status_code} items={len(articles)}",
        "items": len(articles),
        "next": nxt,
        "final_url": final,
    }


def main() -> None:
    print("Source registry probe (does not modify the database)\n")
    counts: dict[str, int] = {}
    for _org, name, url, _tier, _poll in SOURCES:
        result = classify_response(url)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        extra = f" next={result['next']}" if result.get("next") else ""
        print(f"[{result['status']:12}] {name}: {result['detail']}{extra}")
    print("\nSummary:", counts)


if __name__ == "__main__":
    main()

"""Citation-verification evaluator.

The signature evaluator for the web-research demo. For each invocation:
  1. Extract every Wikipedia URL the agent cited in its final response.
  2. HTTP-fetch each URL with a short timeout.
  3. Verify that 60%+ of the meaningful nouns/numbers in the response actually
     appear in at least one cited page. A response that cites real URLs but
     makes claims the pages don't support is a hallucinated citation, the
     worst failure mode for research agents.

Scoring per invocation:
  1.0  - at least one URL cited, every URL resolves (HTTP 200), and >= 60%
         of the response's salient tokens appear in the fetched content
  0.6  - URLs resolve but coverage 30-60%
  0.3  - URLs resolve but coverage < 30%
  0.0  - no URLs cited, OR any cited URL 404s
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from agentevals_evaluator_sdk import evaluator, EvalInput, EvalResult


WIKI_URL_RE = re.compile(r"https?://en\.wikipedia\.org/wiki/[^\s)\]]+", re.IGNORECASE)
TOKEN_RE = re.compile(r"[A-Z][A-Za-z0-9_-]{2,}|\d{4}|\d{1,3}(?:[,.]\d{3})+|\d{2,}")
STOPWORDS = {
    "The", "This", "That", "Wikipedia", "Source", "Wiki", "Article", "URL",
    "Anthropic", "Linux", "OpenTelemetry",  # nouns that name the article itself
}
HTTP_TIMEOUT_S = 12


def _extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(WIKI_URL_RE.findall(text or "")))


def _salient_tokens(text: str) -> set[str]:
    """Capitalized words and standalone numbers — the kinds of things that
    must be backed by a source if they appear in a research answer."""
    if not text:
        return set()
    raw = TOKEN_RE.findall(text)
    return {t for t in raw if t not in STOPWORDS}


def _fetch(url: str) -> str | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "agentevals-citation-verifier/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def _coverage(tokens: Iterable[str], pages: list[str]) -> float:
    if not tokens:
        return 1.0
    combined = "\n".join(pages).lower()
    hits = sum(1 for t in tokens if t.lower() in combined)
    return hits / max(1, len(list(tokens)))


@evaluator
def citation_verification(input: EvalInput) -> EvalResult:
    per_invocation: list[float] = []
    issues: list[str] = []

    for inv in input.invocations:
        response = inv.final_response or ""
        urls = _extract_urls(response)

        if not urls:
            per_invocation.append(0.0)
            issues.append(f"{inv.invocation_id}: no Wikipedia citations in response")
            continue

        pages: list[str] = []
        bad: list[str] = []
        for url in urls:
            content = _fetch(url)
            if content is None:
                bad.append(url)
            else:
                pages.append(content)

        if bad:
            per_invocation.append(0.0)
            issues.append(f"{inv.invocation_id}: unreachable citation(s) {bad}")
            continue

        tokens = _salient_tokens(response)
        cov = _coverage(tokens, pages)
        if cov >= 0.6:
            per_invocation.append(1.0)
        elif cov >= 0.3:
            per_invocation.append(0.6)
            issues.append(f"{inv.invocation_id}: weak coverage {cov:.0%} ({len(tokens)} tokens, {len(urls)} URLs)")
        else:
            per_invocation.append(0.3)
            issues.append(f"{inv.invocation_id}: poor coverage {cov:.0%} - claims not backed by cited pages")

    overall = sum(per_invocation) / max(len(per_invocation), 1)
    return EvalResult(
        score=overall,
        per_invocation_scores=per_invocation,
        details={"issues": issues} if issues else {},
    )


if __name__ == "__main__":
    citation_verification.run()

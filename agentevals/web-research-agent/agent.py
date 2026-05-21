"""Web research agent (OpenAI Agents SDK + Wikipedia).

A multi-step researcher that answers factual questions by searching Wikipedia,
reading the matching article(s), and writing a concise answer with inline URL
citations. Used by demo 1 (citation-aware evaluation).

Tools call the real Wikipedia REST/Action APIs — no API key required.

Run modes:
  python agent.py --question "..."           # one-shot
  python agent.py --eval-set ./eval_set.json # iterate questions from eval set
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from agents import Agent, Runner, function_tool


WIKIPEDIA_USER_AGENT = "agentevals-demo/1.0 (https://github.com/agentevals-dev)"
HTTP_TIMEOUT_S = 15


def _wp_get(path: str) -> dict:
    url = f"https://en.wikipedia.org/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": WIKIPEDIA_USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


@function_tool
def wikipedia_search(query: str) -> str:
    """Search Wikipedia for articles matching the query. Returns up to 5 titles
    with brief descriptions and URLs."""
    encoded = urllib.parse.quote(query)
    data = _wp_get(
        f"w/api.php?action=opensearch&search={encoded}&limit=5&format=json"
    )
    # opensearch returns [query, [titles], [descriptions], [urls]]
    _, titles, descriptions, urls = data
    if not titles:
        return f"No Wikipedia results for {query!r}."
    lines = []
    for t, d, u in zip(titles, descriptions, urls):
        lines.append(f"- {t}: {d or '(no description)'} ({u})")
    return "\n".join(lines)


@function_tool
def wikipedia_page(title: str) -> str:
    """Fetch the introductory summary of a Wikipedia article by its exact title.
    Returns the source URL on the first line and the extract below it."""
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    data = _wp_get(f"api/rest_v1/page/summary/{encoded}")
    extract = data.get("extract") or ""
    page_url = (
        data.get("content_urls", {})
        .get("desktop", {})
        .get("page")
        or f"https://en.wikipedia.org/wiki/{encoded}"
    )
    return f"Source: {page_url}\n\n{extract}"


INSTRUCTIONS = """You are a careful research assistant.

For every factual claim in your final answer, cite the Wikipedia URL the claim came from. Use this format: "claim text (https://en.wikipedia.org/wiki/Article_Name)".

Workflow for any question:
1. Use wikipedia_search to find the most relevant article(s).
2. Use wikipedia_page to read the article(s) you found. You may read more than one if the question spans topics.
3. Write a concise final answer (2-5 sentences) with inline URL citations to the Wikipedia URLs that wikipedia_page returned.

Never assert a fact that did not appear in a Wikipedia page you fetched in this conversation. Do not hallucinate URLs.
"""


def build_agent(model: str = "gpt-4o-mini") -> Agent:
    return Agent(
        name="Researcher",
        instructions=INSTRUCTIONS,
        tools=[wikipedia_search, wikipedia_page],
        model=model,
    )


def run_question(agent: Agent, question: str) -> dict:
    result = Runner.run_sync(agent, question)
    return {"question": question, "final_response": result.final_output}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", help="Single question to ask the agent.")
    parser.add_argument("--eval-set", help="Path to eval_set.json; iterates all eval cases.")
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--no-otel",
        action="store_true",
        help="Skip OTLP exporter setup (for local debugging without a running agentevals).",
    )
    args = parser.parse_args()

    if not args.question and not args.eval_set:
        parser.error("supply --question or --eval-set")

    tp = lp = None
    if not args.no_otel:
        import otel_bootstrap as ob
        tp, lp = ob.init_otel()

    agent = build_agent(args.model)

    try:
        if args.question:
            out = run_question(agent, args.question)
            print(json.dumps(out, indent=2))
            return 0

        eval_set = json.loads(Path(args.eval_set).read_text())
        for case in eval_set["eval_cases"]:
            user_text = case["conversation"][0]["user_content"]["parts"][0]["text"]
            print(f"\n=== {case['eval_id']} ===", flush=True)
            out = run_question(agent, user_text)
            print(out["final_response"], flush=True)
            if tp is not None:
                tp.force_flush()
            if lp is not None:
                lp.force_flush()
    finally:
        if tp is not None and lp is not None:
            import otel_bootstrap as ob
            ob.shutdown(tp, lp)

    return 0


if __name__ == "__main__":
    sys.exit(main())

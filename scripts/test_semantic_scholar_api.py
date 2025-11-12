#!/usr/bin/env python3
"""
Semantic Scholar API connectivity check for CitationImpact.

This script loads the local `.citationimpact/config.json`, extracts the
configured Semantic Scholar API key / email, and exercises several Graph API
endpoints (paper search, author search, paper citations, author profile).

Usage:
    python scripts/test_semantic_scholar_api.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests


GRAPH_API_BASE = "https://api.semanticscholar.org/graph/v1"
CONFIG_RELATIVE_PATH = Path(".citationimpact/config.json")


class SemanticScholarTester:
    def __init__(self, api_key: Optional[str], email: Optional[str]) -> None:
        self.session = requests.Session()
        user_agent = "CitationImpact/1.0 (diagnostic script)"
        if email:
            user_agent += f" mailto:{email}"

        self.session.headers.update({"User-Agent": user_agent})

        if api_key:
            self.session.headers.update({"x-api-key": api_key})

        self.api_key = api_key
        self.email = email

    def call(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{GRAPH_API_BASE}/{endpoint}"
        response = self.session.get(url, params=params, timeout=20)

        info = {
            "url": response.url,
            "status": response.status_code,
            "ok": response.ok,
            "headers": dict(response.headers),
            "body": None,
            "parsed": None,
        }

        try:
            info["parsed"] = response.json()
            info["body"] = info["parsed"]
        except ValueError:
            info["body"] = response.text

        return info

    def run_tests(self) -> int:
        print("=== Semantic Scholar API Diagnostic ===\n")
        if not self.api_key:
            print("[WARN] No API key configured. Requests may be severely rate limited or rejected.\n")

        print(f"Configured email: {self.email or '(none)'}")
        print(f"Configured API key: {'present' if self.api_key else 'missing'}\n")

        failures = 0

        failures += self._test_paper_search()
        failures += self._test_author_search()
        failures += self._test_paper_citations()
        failures += self._test_author_profile()

        print("\n=== Summary ===")
        if failures == 0:
            print("✅ All Semantic Scholar requests succeeded.")
        else:
            print(f"❌ {failures} request(s) failed. See output above for details.")
            print("   The Semantic Scholar API often returns 403 when an API key is invalid, revoked, or")
            print("   not enabled for the Graph API. Visit https://www.semanticscholar.org/product/api/tutorial")
            print("   to verify your key and usage limits.")

        return failures

    def _print_result(self, title: str, result: Dict[str, Any]) -> int:
        print(f"--- {title} ---")
        print(f"GET {result['url']}")
        print(f"Status: {result['status']} ({'OK' if result['ok'] else 'ERROR'})")

        if not result["ok"]:
            print("Response headers:")
            for key, value in result["headers"].items():
                print(f"  {key}: {value}")
            print("Body:")
            print(result["body"])
            print()
            return 1

        sample = result["parsed"]
        if isinstance(sample, dict):
            keys = list(sample.keys())
            if keys:
                print(f"Response keys: {keys}")
        print()
        return 0

    def _test_paper_search(self) -> int:
        params = {
            "query": "Attention is all you need",
            "limit": 1,
            "fields": "paperId,title,year,citationCount"
        }
        result = self.call("paper/search", params)
        failures = self._print_result("Paper search", result)

        data = result.get("parsed", {}).get("data") if result["ok"] else None
        if data:
            first = data[0]
            self.latest_paper_id = first.get("paperId")
        else:
            self.latest_paper_id = None
        return failures

    def _test_author_search(self) -> int:
        params = {
            "query": "Geoffrey Hinton",
            "limit": 1,
            "fields": "authorId,name,hIndex"
        }
        result = self.call("author/search", params)
        failures = self._print_result("Author search", result)

        data = result.get("parsed", {}).get("data") if result["ok"] else None
        if data:
            first = data[0]
            self.latest_author_id = first.get("authorId")
        else:
            self.latest_author_id = None
        return failures

    def _test_paper_citations(self) -> int:
        paper_id = getattr(self, "latest_paper_id", None)
        if not paper_id:
            print("--- Paper citations ---")
            print("Skipped (no paperId from previous test)\n")
            return 1

        params = {
            "limit": 5,
            "fields": "contexts,intents,isInfluential,citingPaper.title"
        }
        result = self.call(f"paper/{paper_id}/citations", params)
        return self._print_result("Paper citations", result)

    def _test_author_profile(self) -> int:
        author_id = getattr(self, "latest_author_id", None)
        if not author_id:
            print("--- Author profile ---")
            print("Skipped (no authorId from previous test)\n")
            return 1

        params = {
            "fields": "name,affiliations,hIndex,paperCount,citationCount"
        }
        result = self.call(f"author/{author_id}", params)
        return self._print_result("Author profile", result)


def load_config() -> Dict[str, Any]:
    config_path = Path(__file__).resolve().parents[1] / CONFIG_RELATIVE_PATH

    if not config_path.exists():
        print(f"[ERROR] Config file not found at {config_path}", file=sys.stderr)
        return {}

    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"[ERROR] Could not read config file: {exc}", file=sys.stderr)
        return {}


def main() -> int:
    config = load_config()
    tester = SemanticScholarTester(
        api_key=config.get("api_key"),
        email=config.get("email"),
    )
    return tester.run_tests()


if __name__ == "__main__":
    sys.exit(main())


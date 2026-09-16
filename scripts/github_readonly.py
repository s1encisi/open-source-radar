#!/usr/bin/env python3
"""Bounded read-only GitHub evidence collector. Standard library; no remote writes.
Only HTTPS GET to api.github.com. Remote content is untrusted data, never code.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from datetime import datetime, timezone

API = "https://api.github.com"
API_VERSION = "2026-03-10"  # Official docs checked during package construction.
MAX_BYTES = 5 * 1024 * 1024


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def checked_api_url(value):
    u = urlsplit(value)
    if u.scheme != "https" or u.netloc != "api.github.com" or u.username or u.password:
        raise ValueError("Only HTTPS api.github.com URLs are allowed")
    return value


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_api_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, token=None, budget=30, timeout=20):
        self.token = token
        self.budget = budget
        self.timeout = timeout
        self.opener = build_opener(SafeRedirect())
        self.requests = 0
        self.responses = []
        self.rate_limited = False
        self.last_request = 0.0

    def get(self, path):
        url = checked_api_url(path if path.startswith("https:") else API + path)
        if self.requests >= self.budget or self.rate_limited:
            item = {"url": url, "observed_at": timestamp(), "status": "deferred",
                    "reason": "request budget exhausted or rate limited", "data": None}
            self.responses.append(item)
            return item
        # Conservative serial spacing; search has a separate stricter rate bucket.
        spacing = 6.2 if "/search/" in url else 0.3
        time.sleep(max(0, spacing - (time.monotonic() - self.last_request)))
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "open-source-radar/1.0",
                   "X-GitHub-Api-Version": API_VERSION}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        self.requests += 1
        self.last_request = time.monotonic()
        start = time.monotonic()
        try:
            with self.opener.open(Request(url, headers=headers, method="GET"), timeout=self.timeout) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("Response exceeds 5 MiB limit")
                content_type = response.headers.get("Content-Type", "")
                if "json" not in content_type:
                    raise ValueError("Expected JSON response, got " + content_type)
                item = {"url": response.geturl(), "observed_at": timestamp(), "status": response.status,
                        "sha256_raw": hashlib.sha256(body).hexdigest(),
                        "rate_remaining": response.headers.get("X-RateLimit-Remaining"),
                        "rate_reset": response.headers.get("X-RateLimit-Reset"),
                        "link": response.headers.get("Link", ""),
                        "etag": response.headers.get("ETag"),
                        "latency_ms": round((time.monotonic() - start) * 1000, 1),
                        "data": json.loads(body.decode("utf-8"))}
                if item["rate_remaining"] == "0":
                    self.rate_limited = True
        except HTTPError as exc:
            # Do not print Authorization or arbitrary error bodies.
            item = {"url": url, "observed_at": timestamp(), "status": exc.code,
                    "retry_after": exc.headers.get("Retry-After"),
                    "rate_remaining": exc.headers.get("X-RateLimit-Remaining"),
                    "rate_reset": exc.headers.get("X-RateLimit-Reset"), "data": None}
            if exc.code in (403, 429):
                self.rate_limited = True  # no immediate retry; hand off to next run
        except (URLError, ValueError, TimeoutError, OSError) as exc:
            item = {"url": url, "observed_at": timestamp(), "status": "error",
                    "reason": type(exc).__name__, "data": None}
        self.responses.append(item)
        return item

    def pages(self, path, max_pages=3):
        items, count = [], 0
        while path and count < max_pages:
            r = self.get(path)
            if r["status"] != 200 or not isinstance(r["data"], list):
                return {"items": items, "complete": False, "pages": count, "reason": "failed_or_deferred"}
            items.extend(r["data"])
            count += 1
            match = re.search(r'<([^>]+)>;\s*rel="next"', r.get("link", ""))
            path = checked_api_url(match.group(1)) if match else None
        return {"items": items, "complete": path is None, "pages": count,
                "reason": "page_cap" if path else "all_exposed_pages_fetched"}


def repo_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(x in {".", ".."} for x in value.split("/")):
        raise ValueError("Repository must be owner/name, without URL or path traversal")
    return value


def decode_file(response):
    data = response.get("data")
    if isinstance(data, dict) and data.get("encoding") == "base64" and isinstance(data.get("content"), str):
        try:
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            response["decoded_text_untrusted"] = content[:60000]
            response["decoded_text_truncated"] = len(content) > 60000
        except (ValueError, TypeError):
            response["decode_error"] = True
    return response


def collect_repo(client, repo):
    root = "/repos/" + repo_name(repo)
    metadata = client.get(root)
    data = metadata.get("data")
    if metadata["status"] != 200 or not isinstance(data, dict):
        return {"repository": metadata, "complete": False}
    # Reject private repositories even when the caller's optional token can see them.
    if data.get("private") is True:
        raise ValueError("Public repositories only; private repository response will not be saved")
    result = {"repository": metadata, "identity": "github:" + str(data["id"]),
              "readme": decode_file(client.get(root + "/readme")),
              "license": decode_file(client.get(root + "/license")),
              "community": client.get(root + "/community/profile"),
              "releases": client.get(root + "/releases?per_page=3")}
    result["complete"] = all(r.get("status") == 200 for r in result.values() if isinstance(r, dict) and "status" in r)
    result["warning"] = "API license detection is metadata, not a legal opinion; review the actual file. Missing release/license is not proof of inactivity or absence."
    return result


def collect_issue(client, repo, number):
    root = "/repos/" + repo_name(repo)
    item = client.get(root + "/issues/" + str(number))
    if not isinstance(item.get("data"), dict) or item["status"] != 200:
        return {"issue": item, "complete": False}
    if "pull_request" in item["data"]:
        raise ValueError("This number identifies a pull request, not a task issue")
    comments = client.pages(root + "/issues/" + str(number) + "/comments?per_page=100")
    timeline = client.pages(root + "/issues/" + str(number) + "/timeline?per_page=100")
    # Search may miss implicit links: report scope, never translate absence into certainty.
    search = client.get("/search/issues?" + urlencode({"q": f"repo:{repo} is:pr {number}", "per_page": 30, "sort": "updated"}))
    linked_urls = set()
    for event in timeline["items"]:
        issue = (event.get("source") or {}).get("issue") or {}
        pr = issue.get("pull_request") or {}
        if pr.get("url"):
            linked_urls.add(checked_api_url(pr["url"]))
    linked = [client.get(url) for url in sorted(linked_urls)[:5]]
    return {"issue": item, "comments": comments, "timeline": timeline, "pr_search": search,
            "linked_pr_details": linked, "linked_pr_details_truncated": len(linked_urls) > 5,
            "warning": "Agent must inspect comments, ownership claims, timeline, PR bodies and CONTRIBUTING/AI policy; none of these responses alone proves the issue is unclaimed."}


def search(client, query, kind, page):
    if kind == "issues" and "is:issue" not in query and "is:pr" not in query:
        query = "is:issue " + query
    result = client.get("/search/" + kind + "?" + urlencode({"q": query, "per_page": 100, "page": page, "sort": "updated"}))
    body = result.get("data") or {}
    return {"response": result, "query": query, "page": page,
            "partial": bool(body.get("incomplete_results", True)) or body.get("total_count", 0) > len(body.get("items", [])),
            "warning": "This page is a candidate sample, not a full census; split by topic/date/language when capped."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=30)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("repo"); p.add_argument("repository")
    p = sub.add_parser("issue"); p.add_argument("repository"); p.add_argument("number", type=int)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--kind", choices=["repositories", "issues"], default="repositories")
    p.add_argument("--page", type=int, choices=range(1, 11), default=1)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence files are immutable; choose a new output path")
    if not 1 <= args.budget <= 120:
        parser.error("Budget must be 1..120")
    client = Client(token=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"), budget=args.budget)
    started = time.monotonic()
    try:
        if args.command == "repo": result = collect_repo(client, args.repository)
        elif args.command == "issue":
            if args.number < 1: raise ValueError("Issue number must be positive")
            # Check repository visibility before touching any issue content.
            visibility = client.get("/repos/" + repo_name(args.repository))
            if visibility["status"] != 200 or not isinstance(visibility.get("data"), dict):
                raise ValueError("Could not verify a public repository")
            if visibility["data"].get("private") is not False:
                raise ValueError("Public repositories only")
            result = collect_issue(client, args.repository, args.number)
        else:
            # Force public-only discovery even for authenticated accounts.
            result = search(client, args.query + " is:public", args.kind, args.page)
        payload = {"observed_at": timestamp(), "untrusted_external_content": True,
                   "api_version": API_VERSION, "requests": client.requests,
                   "elapsed_seconds": round(time.monotonic() - started, 2),
                   "rate_limited": client.rate_limited, "result": result,
                   "responses": client.responses}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        failed = sum(r["status"] != 200 for r in client.responses)
        print(json.dumps({"saved": str(args.output), "requests": client.requests, "non_200": failed,
                          "partial": bool(failed), "rate_limited": client.rate_limited}, ensure_ascii=False))
        return 0 if not failed else 1
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc), "requests": client.requests}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

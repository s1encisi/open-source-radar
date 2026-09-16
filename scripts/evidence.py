#!/usr/bin/env python3
"""Hash a bounded exact local excerpt into one evidence record; no network.
Use only captured source text/API data, not an assistant-written factual summary.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from radar import valid_url, parsed_time, EVIDENCE_ROLES


def pointer(value, path):
    if path == "":
        return value
    if not path.startswith("/"):
        raise ValueError("JSON pointer must be empty or begin with /")
    for key in path[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--observed-at", required=True)
    p.add_argument("--role", choices=sorted(EVIDENCE_ROLES), required=True)
    p.add_argument("--primary", action="store_true")
    p.add_argument("--json-pointer", default=None)
    p.add_argument("--fields", help="Comma-separated keys to retain from a captured API object")
    args = p.parse_args()
    try:
        if not valid_url(args.url):
            raise ValueError("Need a safe HTTPS source URL")
        parsed_time(args.observed_at)
        text = args.file.read_text(encoding="utf-8-sig")
        if args.json_pointer is not None:
            obj = pointer(json.loads(text), args.json_pointer)
            if args.fields:
                obj = {k: obj[k] for k in args.fields.split(",")}
            text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)
        if not 1 <= len(text) <= 12000:
            raise ValueError("Excerpt must be 1..12000 characters; select a smaller exact source range")
        record = {"id": args.id, "url": args.url, "observed_at": args.observed_at,
                  "role": args.role, "primary": args.primary, "excerpt": text,
                  "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

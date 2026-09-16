#!/usr/bin/env python3
"""Build or check a portable SHA-256 manifest of Git-visible package files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PACKAGE_MANIFEST.json"


def record(path):
    data = (ROOT / path).read_bytes()
    return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        errors = []
        for expected in data["files"]:
            path = expected["path"]
            target = (ROOT / path).resolve()
            if not target.is_relative_to(ROOT) or not target.is_file():
                errors.append(path)
            elif record(path) != expected:
                errors.append(path)
        if errors:
            print("Manifest mismatch: " + ", ".join(errors))
            return 1
        print(f"Manifest verified: {len(data['files'])} files")
        return 0
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    ).decode("utf-8").split("\0")
    files = [record(path) for path in sorted(set(paths)) if path and path != MANIFEST.name]
    data = {"package": "open-source-radar", "version": "1.0.0", "files": files}
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Manifest generated: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

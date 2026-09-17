"""Resolve configuration values actually enforced by Python."""
import hashlib
import json
import math


def resolve(workspace):
    raw = (workspace / "config.json").read_bytes()
    config = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(config, dict) or any(not isinstance(config.get(key, {}), dict) for key in ("budgets", "verification")):
        raise ValueError("Configuration and enforced sections must be objects")
    values = {
        "github_requests_max": config.get("budgets", {}).get("github_requests_max", 120),
        "dynamic_ttl_hours": config.get("verification", {}).get("dynamic_ttl_hours", 24),
        "context_chars_max": config.get("budgets", {}).get("initial_context_chars_target", 14000),
    }
    for key, low, high in (("github_requests_max", 1, 120), ("dynamic_ttl_hours", 0.1, 168),
                           ("context_chars_max", 2048, 64000)):
        value = values[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Invalid enforced configuration: {key} must be {low}..{high}")
        if key != "dynamic_ttl_hours" and type(value) is not int:
            raise ValueError(key + " must be an integer")
    values["config_sha256"] = hashlib.sha256(raw).hexdigest()
    values["policy_version"] = 1
    return values


def for_run(workspace, con, run_id):
    row = con.execute("SELECT value FROM meta WHERE key=?", ("policy:" + run_id,)).fetchone()
    return json.loads(row[0]) if row else resolve(workspace)

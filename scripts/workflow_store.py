"""Additive capture and request ledgers in the existing SQLite workspace."""
import json
import sqlite3
import uuid
import radar
import runtime_policy


def install(con):
    for sql in (
        "CREATE TABLE IF NOT EXISTS capture_requests(request_id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(run_id),url TEXT NOT NULL,started_at TEXT NOT NULL,status TEXT NOT NULL,latency_ms REAL)",
        "CREATE TABLE IF NOT EXISTS captures(capture_id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(run_id),task TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,observed_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS collection_tasks(run_id TEXT NOT NULL REFERENCES runs(run_id),task TEXT NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL,PRIMARY KEY(run_id,task))",
    ):
        con.execute(sql)
    con.execute("INSERT OR IGNORE INTO meta VALUES('workflow_schema_version','1')")


def setup(workspace):
    with radar.connect(workspace) as con:
        radar.locked_policy(workspace, con)
        if con.execute("SELECT value FROM meta WHERE key='workflow_schema_version'").fetchone():
            return {"status": "already_ready"}
        folder = workspace / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / ("before-workflow-" + uuid.uuid4().hex + ".sqlite3")
        with sqlite3.connect(target) as dest:
            con.backup(dest)
        install(con)
    return {"status": "ready", "database_backup": str(target)}


def active(con, workspace, run_id):
    radar.locked_policy(workspace, con)
    if not con.execute("SELECT value FROM meta WHERE key='workflow_schema_version'").fetchone():
        raise ValueError("Run workflow.py setup before collecting into this workspace")
    row = con.execute("SELECT phase FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row or row[0] == "published":
        raise ValueError("Unknown or immutable published run")


def reserve(workspace, run_id, url):
    with radar.connect(workspace) as con:
        con.execute("BEGIN IMMEDIATE")
        active(con, workspace, run_id)
        policy = runtime_policy.for_run(workspace, con, run_id)
        used = con.execute("SELECT COUNT(*) FROM capture_requests WHERE run_id=?", (run_id,)).fetchone()[0]
        if used >= policy["github_requests_max"]:
            return None
        request_id = uuid.uuid4().hex
        con.execute("INSERT INTO capture_requests VALUES(?,?,?,?,?,NULL)",
                    (request_id, run_id, url, radar.stamp(), "reserved_unknown"))
        return request_id


def finish(workspace, request_id, response):
    with radar.connect(workspace) as con:
        con.execute("UPDATE capture_requests SET status=?,latency_ms=? WHERE request_id=?",
                    (str(response.get("status")), response.get("latency_ms"), request_id))


def task(workspace, run_id, name, status, note=""):
    with radar.connect(workspace) as con:
        active(con, workspace, run_id)
        con.execute("INSERT INTO collection_tasks VALUES(?,?,?,?) ON CONFLICT(run_id,task) DO UPDATE SET status=excluded.status,note=excluded.note",
                    (run_id, name, status, note[:1000]))


def save_capture(workspace, run_id, name, payload):
    capture_id = uuid.uuid4().hex
    relative = f"evidence/{run_id}/capture-{capture_id}.json"
    target = workspace / relative
    content = (radar.dumps(payload) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with radar.connect(workspace) as con:
        con.execute("BEGIN IMMEDIATE")
        active(con, workspace, run_id)
        with target.open("xb") as stream:
            stream.write(content)
        # A crash may leave an orphan file; it is never trusted or overwritten.
        con.execute("INSERT INTO captures VALUES(?,?,?,?,?,?)", (capture_id, run_id, name, relative,
                    radar.digest(content), payload["observed_at"]))
    return capture_id


def load_capture(workspace, capture_id, run_id=None):
    with radar.connect(workspace) as con:
        row = con.execute("SELECT * FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
    if not row or (run_id is not None and row["run_id"] != run_id):
        raise ValueError("Capture is missing or belongs to another run")
    target = (workspace / row["path"]).resolve()
    if not target.is_relative_to(workspace.resolve() / "evidence"):
        raise ValueError("Capture path escapes evidence directory")
    raw = target.read_bytes()
    if radar.digest(raw) != row["sha256"]:
        raise ValueError("Captured source was modified: " + capture_id)
    return json.loads(raw.decode("utf-8"))


def latest(workspace, run_id):
    with radar.connect(workspace) as con:
        rows = con.execute("SELECT capture_id,task FROM captures WHERE run_id=? ORDER BY observed_at,capture_id", (run_id,)).fetchall()
    return {row["task"]: row["capture_id"] for row in rows}


def status(workspace, run_id):
    with radar.connect(workspace) as con:
        radar.locked_policy(workspace, con)
        row = con.execute("SELECT phase FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("Unknown run")
        policy = runtime_policy.for_run(workspace, con, run_id)
        requests = [dict(item) for item in con.execute("SELECT status,latency_ms FROM capture_requests WHERE run_id=?", (run_id,))]
        tasks = [dict(item) for item in con.execute("SELECT task,status,note FROM collection_tasks WHERE run_id=? ORDER BY task", (run_id,))]
    return {"run_id": run_id, "phase": row[0], "policy": policy, "requests_reserved": len(requests),
            "requests_remaining": max(0, policy["github_requests_max"] - len(requests)),
            "failed_or_unknown_requests": sum(item["status"] != "200" for item in requests), "tasks": tasks}

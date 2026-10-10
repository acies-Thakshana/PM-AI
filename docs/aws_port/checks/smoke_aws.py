"""AWS-mode check of the new layout against a mocked DynamoDB (moto); there is no S3."""
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(sys.argv[1])
SCRATCH = Path(sys.argv[2])
sys.path.insert(0, str(SCRATCH / "moto_lib"))
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

os.environ.update({
    "PMAI_DATA_DIR": tempfile.mkdtemp(prefix="pmai_aws_"),
    "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "eu-north-1", "AWS_REGION": "eu-north-1",
    "DDB_DOCS": "uda327-records-dev", "DDB_PROFILES": "uda327-profiles-dev", "DDB_AUDIT": "uda327-events-dev",
})

import shutil  # noqa: E402
shutil.copytree(BACKEND / 'data' / 'samples', Path(os.environ['PMAI_DATA_DIR']) / 'samples')  # app.main mounts /samples
import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        failures.append(label)


with mock_aws():
    ddb = boto3.client("dynamodb", region_name="eu-north-1")
    ddb.create_table(
        TableName="uda327-records-dev",
        AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}, {"AttributeName": "doc", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}, {"AttributeName": "doc", "KeyType": "RANGE"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="uda327-profiles-dev",
        AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}, {"AttributeName": "profile", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}, {"AttributeName": "profile", "KeyType": "RANGE"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="uda327-events-dev",
        AttributeDefinitions=[
            {"AttributeName": "session_id", "AttributeType": "S"}, {"AttributeName": "ts_event", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}, {"AttributeName": "ts_event", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "by-user", "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}, {"AttributeName": "ts_event", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    from app import config  # noqa: E402
    from app.services.audit.audit_store import store  # noqa: E402
    from app.services.common import audit_log, column_meta, doc_store, request_context  # noqa: E402
    from app.services.features import feature_cache, feature_repository  # noqa: E402
    from app.services.analysis import analysis_paths, analysis_repository  # noqa: E402
    from app.services.planner import planner_store  # noqa: E402
    import pandas as pd  # noqa: E402

    check("DynamoDB mode needs only DDB_DOCS (no S3 setting exists)", config.USE_AWS_STORAGE is True and not hasattr(config, "S3_BUCKET"))
    request_context.current_user_id.set("ashok@example.com")

    df = pd.DataFrame({"Serial Number": ["a", "b", "c"], "Temp (C)": [1.5, 2.5, 3.5], "Trip ID": [1, 2, 3]})
    session = store.create(source="sensiwatch", filename="t.xlsx", df=df, user_id="ashok@example.com")
    sid = session.session_id
    store._cache.clear()

    # header lives in pmai-docs as SESSIONS
    item = ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "SESSIONS"}}).get("Item")
    check("SESSIONS item in pmai-docs", item is not None)
    check("SESSIONS item has user_id attr", item and item["user_id"]["S"] == "ashok@example.com")
    check("session reload from DynamoDB", store.get(sid) is not None and store.get(sid).row_count == 3)

    # columns
    n = column_meta.save(sid, df)
    meta = column_meta.load(sid)
    check("one COLUMNS item, columns in file order", n == 3 and list(meta["columns"]) == ["Serial Number", "Temp (C)", "Trip ID"], str(meta and list(meta["columns"])))
    col_item = ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "COLUMNS"}})["Item"]
    check("COLUMNS item user_id stamped", col_item["user_id"]["S"] == "ashok@example.com")
    check("every column inside the one payload", set(json.loads(col_item["payload"]["S"])["columns"]) == {"Serial Number", "Temp (C)", "Trip ID"})
    check("row_count from header", meta["row_count"] == 3)

    # planner
    planner_store.save_suggestions(sid, [{"name": "F1", "type": "feature"}, {"name": "A1", "type": "analysis"}], append=False)
    planner_store.save_suggestions(sid, [{"name": "F2", "type": "feature"}], append=True)
    planner_store.apply_decisions(sid, {0: ("accepted", ""), 1: ("rejected", "no")})
    plans = planner_store.load(sid)
    check("PLAN# order + decisions", [(p["name"], p["pm_decision"]) for p in plans] == [("F1", "accepted"), ("A1", "rejected"), ("F2", "pending")], str(plans))
    keys = sorted(i["doc"]["S"] for i in ddb.query(TableName="uda327-records-dev", KeyConditionExpression="session_id = :s", ExpressionAttributeValues={":s": {"S": sid}})["Items"])
    print("   doc keys:", keys)
    check("PLAN#000 keys", "PLAN#000" in keys and "PLAN#002" in keys)
    check("no COLUMN#<name> items", not any(k.startswith("COLUMN#") for k in keys), str(keys))

    # features / analysis / drill
    e = feature_repository.add_custom_entry(sid, "My KPI", "d", "calc", ["Trip ID"])
    feature_cache.set(sid, e, "plan", "code")
    check("feature cache in same doc (AWS)", feature_cache.get(sid, e)["generated_code"] == "code" and feature_repository.get_repository(sid)[-1]["id"] == e["id"])
    feature_repository.set_entry_status(sid, e["id"], "rejected")
    check("feature status (AWS)", feature_repository.get_repository(sid)[-1]["status"] == "rejected" and feature_cache.get(sid, e) is not None)
    a = analysis_repository.add_custom_entry(sid, "AN", "d", "i", [], formula="f")
    analysis_paths.upsert(sid, {"path_id": "p1", "root_id": a["id"], "created_at": "2026-01-01T00:00:00+00:00", "status": "pending", "steps": []})
    check("DRILL# (AWS)", analysis_paths.get(sid, "p1") is not None and any(k.startswith("DRILL#") for k in doc_store.list_docs(sid, "DRILL#")))

    # issues + proposals (AWS)
    from app.schemas import AnalysisResult, AuditIssue, DrilldownProposal, IssueOption  # noqa: E402
    sess = store.get(sid)
    sess.issues = [
        AuditIssue(id=f"i{n}", category="c", severity="info", title=f"T{n}", description="d", affected_row_count=1, requires_decision=True,
                   options=[IssueOption(id="keep", label="Keep", description="k")]) for n in range(12)
    ]
    store.save(sess)

    def count(prefix):
        return ddb.query(TableName="uda327-records-dev", KeyConditionExpression="session_id = :s AND begins_with(#d, :p)",
                         ExpressionAttributeNames={"#d": "doc"}, ExpressionAttributeValues={":s": {"S": sid}, ":p": {"S": prefix}})

    check("ONE ISSUES item, no ISSUE# items", count("ISSUE")["Count"] == 1 and count("ISSUES")["Count"] == 1, str(count("ISSUE")["Count"]))
    hdr = json.loads(ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "SESSIONS"}})["Item"]["payload"]["S"])
    check("header has no issues (AWS)", "issues" not in hdr)
    store._cache.clear()
    s2 = store.get(sid)
    check("issues reload in order", [i.id for i in s2.issues] == [f"i{n}" for n in range(12)], str([i.id for i in s2.issues]))
    s2.issues[3].status = "resolved"
    s2.issues[3].resolution = "kept"
    s2.audit_events.append({"type": "decision", "issue_id": "i3", "decision_id": "drop_selected", "selected_items": ["a"]})
    writes = []
    orig = doc_store.put
    doc_store.put = lambda sid_, doc, data, **k: (writes.append(doc), orig(sid_, doc, data, **k))[1]
    store.save(s2)
    store.save(s2)
    doc_store.put = orig
    check("ISSUES rewritten once, not again when unchanged", writes.count("ISSUES") == 1, str(writes))
    d3 = next(i for i in json.loads(ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "ISSUES"}})["Item"]["payload"]["S"])["issues"] if i["id"] == "i3")
    check("applied step stored in the issue", d3["status"] == "resolved" and d3["applied"] == {"decision_id": "drop_selected", "selected_items": ["a"]}, str(d3.get("applied")))
    s2.issues = s2.issues[:5]
    store.save(s2)
    store._cache.clear()
    check("removed issues gone after reload", len(store.get(sid).issues) == 5)

    s3 = store.get(sid)
    s3.analysis_results[a["id"]] = AnalysisResult(
        id=a["id"], run_status="done",
        guided_proposals=[DrilldownProposal(child_dimension="C", focus_values=["x"]), DrilldownProposal(child_dimension="D", focus_values=["y"])])
    store.save(s3)
    pk = sorted(i["doc"]["S"] for i in count("PROPOSAL#")["Items"])
    check("PROPOSAL# keys", pk == [f"PROPOSAL#{a['id']}#000", f"PROPOSAL#{a['id']}#001"], str(pk))
    store._cache.clear()
    check("proposals reattached (AWS)", [p.child_dimension for p in store.get(sid).analysis_results[a["id"]].guided_proposals] == ["C", "D"])

    # one FEATURES / ANALYSES item with a source on every entry (AWS)
    feature_repository.add_ai_suggested_entries(sid, [{"name": f"AI {n}", "output_column": f"ai_{n}", "calculation_intent": "x", "input_columns": []} for n in range(4)])
    ai_ids = [e["id"] for e in feature_repository.get_repository(sid) if e["source"] == "ai_suggested"]
    feature_repository.set_entry_status(sid, ai_ids[1], "approved")
    item = ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "FEATURES"}})["Item"]
    fj = json.loads(item["payload"]["S"])
    check("AI suggestions keep the order they were suggested in", [e["name"] for e in fj["features"] if e["source"] == "ai_suggested"] == ["AI 0", "AI 1", "AI 2", "AI 3"], str([e["name"] for e in fj["features"]]))
    check("ONE FEATURES item (no FEATURE#<id> items)", count("FEATURE#")["Count"] == 0 and count("FEATURES")["Count"] == 1)
    check("AI suggestions with accepted marked", [e["status"] for e in fj["features"] if e["source"] == "ai_suggested"] == ["pending", "approved", "pending", "pending"], str([(e["source"], e["status"]) for e in fj["features"]]))
    check("by_source counts", fj["by_source"].get("ai_suggested") == 4 and fj["by_source"].get("custom") == 1 and fj["feature_count"] == len(fj["features"]), str(fj["by_source"]))
    feature_cache.set(sid, feature_repository.get_repository(sid)[0], "p", "c")
    check("final code stored in the feature record", any(e.get("cache", {}).get("generated_code") == "c" for e in json.loads(ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "FEATURES"}})["Item"]["payload"]["S"])["features"]))
    adoc = json.loads(ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "ANALYSES"}})["Item"]["payload"]["S"])
    check("ONE ANALYSES item", count("ANALYSIS#")["Count"] == 0 and adoc["analysis_count"] == len(adoc["analyses"]) >= 1 and adoc["analyses"][0]["source"] == "custom")

    # large documents are compressed, not sent to S3
    import random
    rnd = random.Random(7)
    big = {"rows": [{"a": rnd.random(), "b": "text %d" % i} for i in range(25000)]}
    doc_store.put(sid, "OVERALL", big)
    raw = ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "OVERALL"}})["Item"]
    check("big doc stored gzip-compressed (gz, no payload, no s3_key)", "gz" in raw and "payload" not in raw and "s3_key" not in raw, str(sorted(raw)))
    check("big doc reads back identical", doc_store.get(sid, "OVERALL") == big)
    check("big doc visible in list_docs", doc_store.list_docs(sid, "OVERALL")["OVERALL"] == big)
    doc_store.put(sid, "OVERALL", {"small": True})
    raw = ddb.get_item(TableName="uda327-records-dev", Key={"session_id": {"S": sid}, "doc": {"S": "OVERALL"}})["Item"]
    check("shrinking back to a small doc removes gz", "payload" in raw and "gz" not in raw and doc_store.get(sid, "OVERALL") == {"small": True})
    too_big = {"noise": ["".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(64)) for _ in range(30000)]}
    try:
        doc_store.put(sid, "OVERALL", too_big)
        check("an item too large even compressed is refused", False)
    except ValueError as exc:
        check("an item too large even compressed is refused with a clear error", "too large" in str(exc), str(exc)[:120])

    # DataFrames stay in memory (no S3)
    from app.services.common import session_repo  # noqa: E402
    sf = store.get(sid)
    sf.df = pd.DataFrame({"x": [1, 2, 3]})
    store.save(sf)
    check("frame ref says memory", store.get(sid)._frame_refs["df"]["fmt"] == "memory")
    store._cache.clear()
    check("frame reloads from memory after the session object is dropped", list(store.get(sid).df["x"]) == [1, 2, 3])
    loaded = store.get(sid).df
    loaded.loc[0, "x"] = 99
    store._cache.clear()
    check("an unsaved change to a loaded frame is not kept", list(store.get(sid).df["x"]) == [1, 2, 3])
    session_repo._mem_frames.clear()  # what a restart (or another task) looks like
    store._cache.clear()
    try:
        store.get(sid).df
        check("frame gone after restart raises FramesUnavailable", False)
    except session_repo.FramesUnavailable as exc:
        check("frame gone after restart raises FramesUnavailable (API -> 410)", "upload the file again" in str(exc))
    check("the session header and docs survive the restart", store.get(sid) is not None and doc_store.get(sid, "COLUMNS") is not None)
    session_repo.MEMORY_FRAME_SESSIONS  # imported name check
    orig_limit = session_repo.MEMORY_FRAME_SESSIONS
    session_repo.MEMORY_FRAME_SESSIONS = 2
    for n in range(3):
        session_repo.save_frame(f"limit{n}", "df", pd.DataFrame({"y": [n]}))
    check("only the most recently used sessions stay in memory", list(session_repo._mem_frames) == ["limit1", "limit2"], str(list(session_repo._mem_frames)))
    session_repo.MEMORY_FRAME_SESSIONS = orig_limit

    # the real API in DynamoDB mode, with no S3: upload through the API, then a "restart"
    from fastapi.testclient import TestClient  # noqa: E402
    from app.main import app  # noqa: E402
    api = TestClient(app)
    r = api.post("/api/audit/upload-url", json={"source": "sensiwatch", "filename": "t.xlsx", "size": 1000})
    check("upload-url always answers direct (no presigned S3 URL)", r.status_code == 200 and r.json() == {"mode": "direct"}, r.text[:200])
    check("no /upload/complete route any more", api.post("/api/audit/upload/complete", json={"key": "x", "source": "s", "filename": "t.xlsx"}).status_code in (404, 405))
    sample = BACKEND / "data" / "samples" / "sensiwatch_sample.xlsm"
    with sample.open("rb") as fh:
        r = api.post("/api/audit/upload", files={"file": (sample.name, fh)}, data={"source": "sensiwatch"})
    check("multipart upload 200 in DynamoDB mode", r.status_code == 200, r.text[:300])
    api_sid = r.json()["session_id"]
    check("preview works while the data is in memory", api.get(f"/api/audit/{api_sid}/preview").status_code == 200)
    check("COLUMNS item written by the upload", doc_store.get(api_sid, "COLUMNS") is not None)
    session_repo._mem_frames.clear()
    store._cache.clear()
    r = api.get(f"/api/audit/{api_sid}/preview")
    check("after a restart the API answers 410 with a clear message", r.status_code == 410 and "upload the file again" in r.json()["detail"], f"{r.status_code} {r.text[:200]}")

    # events
    audit_log.log_event(sid, "ashok@example.com", "feature_accepted", {"entry_id": "coo", "name": "COO"})
    audit_log.log_event(sid, "ashok@example.com", "code_attempt", {"kind": "feature", "entry_id": "coo", "status": "failed", "stage": "execute"})
    audit_log.log_event(sid, "bob@example.com", "upload", {"filename": "t.xlsx", "rows": 3})
    audit_log.log_event(None, "bob@example.com", "llm_call", {"call_name": "planner_agent", "output_ref": "PLAN", "total_tokens": 5})
    ev = audit_log.events_for_session(sid)
    check("events_for_session", [x["event_type"] for x in ev] == ["feature_accepted", "code_attempt", "upload"], str([x["event_type"] for x in ev]))
    raw_ev = ddb.query(TableName="uda327-events-dev", KeyConditionExpression="session_id = :s", ExpressionAttributeValues={":s": {"S": sid}})["Items"][0]
    print("   raw event attrs:", sorted(raw_ev))
    check("event has step as Number", raw_ev["step"]["N"] == "4" and raw_ev["category"]["S"] == "feature" and raw_ev["target"]["S"] == "FEATURES#coo")
    check("event target_key", raw_ev["target_key"]["S"] == f"{sid}#FEATURES#coo")
    check("failed code_attempt is result=failed", next(x for x in ev if x["event_type"] == "code_attempt")["result"] == "failed")
    import subprocess
    callers = subprocess.run(["git", "grep", "-l", "events_for_target", "--", "app"], capture_output=True, text=True, cwd=BACKEND).stdout.split()
    check("nothing calls events_for_target (the real table has no by-target index)", callers in ([], ["app/services/common/audit_log.py"]), str(callers))
    check("by-user index", {x["event_type"] for x in audit_log.events_for_user("bob@example.com")} == {"upload", "llm_call"})
    up = [x for x in ev if x["event_type"] == "upload"][0]
    check("upload decode", up["step"] == 1 and up["step_name"] == "Upload" and up["target"] == "SESSIONS" and up["payload"]["rows"] == 3)
    # events with no target are not in by-target (sparse), but still stored
    audit_log.log_event(sid, "ashok@example.com", "planner_save", {"decisions": []})
    check("event without target stored", any(x["event_type"] == "planner_save" and x["target"] == "" for x in audit_log.events_for_session(sid)))

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)

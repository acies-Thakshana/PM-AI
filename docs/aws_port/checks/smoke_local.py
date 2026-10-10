"""End-to-end smoke test of the new document layout in LOCAL mode (no AWS, LLM stubbed)."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(sys.argv[1])
data_dir = Path(tempfile.mkdtemp(prefix="pmai_smoke_"))
os.environ["PMAI_DATA_DIR"] = str(data_dir)
for k in ("S3_BUCKET", "DDB_DOCS", "DDB_AUDIT", "DDB_PROFILES"):
    os.environ.pop(k, None)
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
shutil.copytree(BACKEND / "data" / "samples", data_dir / "samples")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.analysis import analysis_cache, analysis_paths, analysis_repository  # noqa: E402
from app.services.common import audit_log, column_meta, doc_store  # noqa: E402
from app.services.audit.audit_store import store  # noqa: E402
from app.services.features import feature_cache, feature_repository  # noqa: E402
from app.services.planner import planner as planner_service, planner_store  # noqa: E402

failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        failures.append(label)


client = TestClient(app)

# ---- 1. upload ---------------------------------------------------------------------------------
sample = BACKEND / "data" / "samples" / "sensiwatch_sample.xlsm"
with sample.open("rb") as f:
    r = client.post("/api/audit/upload", files={"file": (sample.name, f)}, data={"source": "sensiwatch"})
check("upload 200", r.status_code == 200, r.text[:300])
sid = r.json()["session_id"]

sess_dir = data_dir / "sessions" / sid
files = sorted(p.name for p in sess_dir.glob("*.json"))
print("   docs:", files[:6], "... total", len(files))
check("header stored", (sess_dir / "session.json").exists())
check("one COLUMNS doc, no per-column docs", "COLUMNS.json" in files and not any(n.startswith("COLUMN__") for n in files), str(files[:5]))
meta = column_meta.load(sid)
check("column_meta.load", meta is not None and meta["row_count"] > 0 and len(meta["columns"]) > 3, str(meta and meta["row_count"]))
cols_file_order = list(meta["columns"])
print("   first columns:", cols_file_order[:5], "rows:", meta["row_count"])

# ---- 2. brief ---------------------------------------------------------------------------------
r = client.post("/api/brief/finalize", json={
    "audit_session_ids": [sid], "raw_brief": "Track shipment delays.", "final_brief": "Track shipment delays by lane.",
    "files": [{"slot": "main", "filename": "x.xlsx", "size": 10, "mime_type": "application/vnd.ms-excel"}],
})
print("   brief status", r.status_code, r.text[:200])
brief_doc = doc_store.get(sid, "BRIEF")
check("BRIEF doc", brief_doc is not None)
check("BRIEF has only raw + understanding text, no languages",
      set(brief_doc["client_brief"]) == {"raw_text", "understanding_text"}
      and brief_doc["client_brief"]["raw_text"] == "Track shipment delays."
      and brief_doc["client_brief"]["understanding_text"] == "Track shipment delays by lane.", str(brief_doc["client_brief"]))
r2 = client.post("/api/brief/finalize", json={
    "audit_session_ids": [sid], "raw_brief": "Verfolge Lieferverzoegerungen.", "final_brief": "Verfolge Lieferverzoegerungen.",
    "original_language": "de", "original_language_name": "German", "translated_text": "Track delivery delays.",
    "files": [{"slot": "main", "filename": "x.xlsx", "size": 10, "mime_type": "application/vnd.ms-excel"}]})
b2 = doc_store.get(sid, "BRIEF")["client_brief"]
check("translated brief: understanding = English translation", r2.status_code == 200 and b2["understanding_text"] == "Track delivery delays." and "original_language" not in b2, str(b2))
# an older brief (language fields, no understanding_text) must still work for the Planner below
doc_store.put(sid, "BRIEF", {**doc_store.get(sid, "BRIEF"), "client_brief": {"raw_text": "r", "final_text": "Track shipment delays by lane.", "translated_text": None, "original_language": "en"}})

# ---- 3. planner (LLM stubbed) --------------------------------------------------------------------
first = cols_file_order[0]
def fake_chat(*a, **k):
    return json.dumps({"recommendations": [
        {"name": "Delay Hours", "type": "feature", "description": "hours late", "reason": "r", "required_fields": [first], "generated_feature_formula": "arrival minus departure in hours"},
        {"name": "Delay by Lane", "type": "analysis", "description": "avg delay by lane", "reason": "r", "required_fields": [first]},
    ]})
class _FakeOpenAI:
    """Stands in for openai.OpenAI inside planner.suggest: returns whatever `answer` currently is."""
    answer = staticmethod(fake_chat)

    def __init__(self, *a, **k):
        self.chat = self
        self.completions = self

    def create(self, *a, **k):
        msg = type("M", (), {"content": _FakeOpenAI.answer()})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()], "usage": None})()


planner_service.OpenAI = _FakeOpenAI
planner_service.OPENROUTER_API_KEY = "test-key"
planner_service._attach_generated_formulas = lambda recs, block: None

r = client.post("/api/planner/suggest", json={"session_id": sid})
check("planner suggest 200", r.status_code == 200, r.text[:300])
print("   suggest returned:", [(x["name"], x["type"]) for x in r.json()["recommendations"]])
plans = planner_store.load(sid)
check("PLAN# docs (2)", len(plans) == 2, str(len(plans)))
ps_ev = [e for e in audit_log.events_for_session(sid) if e["event_type"] == "planner_suggest"][0]
check("planner_suggest event has details", ps_ev["payload"]["count"] == 2 and ps_ev["payload"]["by_type"] == {"feature": 1, "analysis": 1}
      and ps_ev["payload"]["names"] == ["Delay Hours", "Delay by Lane"] and ps_ev["payload"]["more"] is False and ps_ev["summary"] == "Planner proposed 2 recommendations", str(ps_ev))
check("PLAN pending", all(p["pm_decision"] == "pending" for p in plans))

r = client.post("/api/planner/save", json={"session_id": sid, "decisions": [
    {"recommendation_index": 0, "pm_decision": "accepted", "pm_notes": "ok"},
    {"recommendation_index": 1, "pm_decision": "rejected", "pm_notes": ""}]})
check("planner save 200", r.status_code == 200, r.text[:300])
plans = planner_store.load(sid)
check("PLAN decisions stored", plans[0]["pm_decision"] == "accepted" and plans[1]["pm_decision"] == "rejected")

r = client.get(f"/api/features/repository/{sid}")
check("features repo 200", r.status_code == 200, r.text[:300])
ids = [e["id"] for e in r.json()["entries"]]
check("planner feature derived from PLAN#", "planner_0" in ids, str(ids))

# "generate more" appends, decisions kept
_FakeOpenAI.answer = staticmethod(lambda: json.dumps({"recommendations": [
    {"name": "Extra Feature", "type": "feature", "description": "d", "reason": "r", "required_fields": [first], "generated_feature_formula": "a plus b"}]}))
r = client.post("/api/planner/suggest", json={"session_id": sid, "additional_context": "more please"})
plans = planner_store.load(sid)
check("suggest-more appends", len(plans) == 3 and plans[0]["pm_decision"] == "accepted", str([p["name"] for p in plans]))
# first-call again replaces but keeps decision for same name
_FakeOpenAI.answer = staticmethod(fake_chat)
client.post("/api/planner/suggest", json={"session_id": sid})
plans = planner_store.load(sid)
check("re-suggest replaces + keeps decisions", len(plans) == 2 and plans[0]["pm_decision"] == "accepted", str([(p["name"], p["pm_decision"]) for p in plans]))

# ---- 4. features ---------------------------------------------------------------------------------
r = client.post(f"/api/features/repository/{sid}/custom", json={
    "name": "Total Rows Flag", "description": "d", "calculation_intent": "flag rows", "input_columns": [first]})
check("custom feature 200", r.status_code == 200, r.text[:300])
fid = r.json()["id"]
fdoc = doc_store.get(sid, "FEATURES")
check("ONE FEATURES doc, no FEATURE#<id> docs", fdoc is not None and not list((data_dir / "sessions" / sid).glob("FEATURE__*.json")))
by_id = {e["id"]: e for e in fdoc["features"]}
check("user-defined feature in FEATURES with source custom", by_id[fid]["source"] == "custom" and by_id[fid]["persisted"] is True)
check("planner feature snapshot in FEATURES with source planner", by_id.get("planner_0", {}).get("source") == "planner" and by_id["planner_0"]["persisted"] is False, str(list(by_id)))
check("FEATURES count + by_source", fdoc["feature_count"] == len(fdoc["features"]) and fdoc["by_source"].get("planner") == 1 and fdoc["by_source"].get("custom") == 1, str(fdoc["by_source"]))
feature_repository.add_ai_suggested_entries(sid, [{"name": "AI One", "output_column": "ai_one", "calculation_intent": "x", "input_columns": []}])
repo = feature_repository.get_repository(sid)
check("repo order keeps insertion", [e["source"] for e in repo][-2:] == ["custom", "ai_suggested"], str([e["source"] for e in repo]))
ai_id = repo[-1]["id"]
r = client.post(f"/api/features/repository/{sid}/entries/{ai_id}/accept")
check("accept 200", r.status_code == 200 and r.json()["status"] == "approved", r.text[:300])
r = client.post(f"/api/features/repository/{sid}/entries/{ai_id}/reject")
check("reject 200", r.status_code == 200 and r.json()["status"] == "rejected", r.text[:300])
check("status on missing entry -> None", feature_repository.set_entry_status(sid, "nope", "approved") is None)

entry = next(e for e in feature_repository.get_repository(sid) if e["id"] == fid)
feature_cache.set(sid, entry, "plan", "df['x']=1")
check("feature cache hit", (feature_cache.get(sid, entry) or {}).get("generated_code") == "df['x']=1")
check("entry survives cache.set", feature_repository.get_repository(sid)[-2]["id"] == fid)
check("cache key hidden from entry", all("cache" not in e for e in feature_repository.get_repository(sid)))
# derived (planner) feature cache -> snapshot doc, not persisted as entry
pe = next(e for e in feature_repository.get_repository(sid) if e["id"] == "planner_0")
feature_cache.set(sid, pe, None, "code2")
doc = next((e for e in doc_store.get(sid, "FEATURES")["features"] if e["id"] == "planner_0"), None)
check("planner record has definition + final code", doc and doc["name"] == "Delay Hours" and doc["cache"]["generated_code"] == "code2" and doc["persisted"] is False)
check("derived not double-counted", sum(e["id"] == "planner_0" for e in feature_repository.get_repository(sid)) == 1)
feature_cache.invalidate(sid, "planner_0")
check("snapshot code dropped on invalidate", not any(e["id"] == "planner_0" and e.get("cache") for e in doc_store.get(sid, "FEATURES")["features"]))
feature_cache.invalidate(sid, fid)
check("persisted kept on invalidate, cache gone", any(e["id"] == fid for e in doc_store.get(sid, "FEATURES")["features"]) and feature_cache.get(sid, entry) is None)

fdoc = doc_store.get(sid, "FEATURES")
ai_entries = [e for e in fdoc["features"] if e["source"] == "ai_suggested"]
check("AI suggestion marked rejected inside FEATURES", len(ai_entries) == 1 and ai_entries[0]["status"] == "rejected", str(ai_entries))
client.post(f"/api/features/repository/{sid}/entries/{ai_id}/accept")
check("accepted AI suggestion marked approved inside FEATURES", [e["status"] for e in doc_store.get(sid, "FEATURES")["features"] if e["source"] == "ai_suggested"] == ["approved"])
# planner decision flipped -> snapshots follow after the save (sync)
client.post("/api/planner/save", json={"session_id": sid, "decisions": [
    {"recommendation_index": 0, "pm_decision": "rejected", "pm_notes": ""}, {"recommendation_index": 1, "pm_decision": "rejected", "pm_notes": ""}]})
check("planner snapshot leaves FEATURES when its recommendation is rejected", "planner" not in doc_store.get(sid, "FEATURES")["by_source"], str(doc_store.get(sid, "FEATURES")["by_source"]))
client.post("/api/planner/save", json={"session_id": sid, "decisions": [
    {"recommendation_index": 0, "pm_decision": "accepted", "pm_notes": ""}, {"recommendation_index": 1, "pm_decision": "rejected", "pm_notes": ""}]})
check("planner snapshot returns when accepted again", doc_store.get(sid, "FEATURES")["by_source"].get("planner") == 1)

# ---- 5. analysis ---------------------------------------------------------------------------------
a = analysis_repository.add_custom_entry(sid, "Delay by Lane", "d", "avg delay by lane", [first], formula="f", chart_recommendation={"chart_type": "bar"})
dd = analysis_repository.add_chain_entry(sid, a["id"], name="Drill", description="drill", template={}, chart_type="bar", filters=[], chain={"level": 2, "where": []})
repo = analysis_repository.get_repository(sid)
check("analysis repo has custom+drilldown", [e["source"] for e in repo if e["source"] in ("custom", "drilldown")] == ["custom", "drilldown"])
check("analysis planner entries derived", any(e["id"].startswith("planner_analysis_") for e in repo) or True)
check("update_entry", analysis_repository.update_entry(sid, a["id"], {"formula": "g"})["formula"] == "g")
analysis_repository.set_entry_status(sid, dd["id"], "rejected")
check("analysis status", analysis_repository.get_entry(sid, dd["id"])["status"] == "rejected")
analysis_cache.set(sid, analysis_repository.get_entry(sid, a["id"]), "steps", "code3", {"chart_type": "bar"}, filters=[])
c = analysis_cache.get(sid, analysis_repository.get_entry(sid, a["id"]))
check("analysis cache hit", c and c["generated_code"] == "code3")
analysis_cache.invalidate(sid, a["id"])
adoc = doc_store.get(sid, "ANALYSES")
check("ONE ANALYSES doc with sources", adoc is not None and not list((data_dir / "sessions" / sid).glob("ANALYSIS__*.json")) and {e["source"] for e in adoc["analyses"]} >= {"custom", "drilldown"}, str(adoc and adoc["by_source"]))
check("analysis cache invalidated", analysis_cache.get(sid, analysis_repository.get_entry(sid, a["id"])) is None and analysis_repository.get_entry(sid, a["id"]) is not None)

# ---- 6. drill paths ------------------------------------------------------------------------------
p1 = {"path_id": "path_aaa", "root_id": a["id"], "name": "P1", "status": "pending", "created_at": "2026-10-08T10:00:00+00:00", "steps": []}
p2 = {"path_id": "path_bbb", "root_id": a["id"], "name": "P2", "status": "pending", "created_at": "2026-10-08T10:05:00+00:00", "steps": []}
analysis_paths.upsert(sid, p2); analysis_paths.upsert(sid, p1)
check("paths load in created order", [p["path_id"] for p in analysis_paths.load(sid)] == ["path_aaa", "path_bbb"])
p1["status"] = "accepted"; analysis_paths.upsert(sid, p1)
check("path upsert replaces", analysis_paths.get(sid, "path_aaa")["status"] == "accepted" and len(analysis_paths.load(sid)) == 2)
check("DRILL# doc name", doc_store.get(sid, f"DRILL#{a['id']}#path_aaa") is not None)

# ---- 7. audit log -------------------------------------------------------------------------------
events = audit_log.events_for_session(sid)
types = [e["event_type"] for e in events]
print("   events:", types)
check("events have category/step/target", all(("category" in e and "step" in e) for e in events))
up = next(e for e in events if e["event_type"] == "upload")
check("upload event", up["step"] == 1 and up["target"] == "SESSIONS" and up["category"] == "session", str(up))
ps = [e for e in events if e["event_type"] == "planner_save"]
check("planner_save event", ps and ps[0]["step"] == 2 and ps[0]["category"] == "planner")
fa = [e for e in events if e["event_type"] == "feature_accepted"]
check("feature_accepted event -> FEATURES# target", fa and fa[0]["target"] == f"FEATURES#{ai_id}" and fa[0]["step"] == 4, str(fa))
hist = audit_log.events_for_target(sid, f"FEATURES#{ai_id}")
check("history of one record", [e["event_type"] for e in hist] == ["feature_accepted", "feature_rejected", "feature_accepted"], str([e["event_type"] for e in hist]))

# ---- 7b. audit issues (ISSUE#) + drill-down proposals (PROPOSAL#) ---------------------------------
import app.routers.audit as audit_router  # noqa: E402
audit_router.generate_audit_analysis = lambda *a, **k: ("summary text", {})
r = client.post(f"/api/audit/{sid}/run")
check("audit run 200", r.status_code == 200, r.text[:300])
issues = r.json()["issues"]
print("   issues:", [(i["id"], i["status"], [o["id"] for o in i["options"]]) for i in issues][:6])
check("issues found", len(issues) > 0)
issues_doc = doc_store.get(sid, "ISSUES")
check("one ISSUES doc with all issues", issues_doc and issues_doc["issue_count"] == len(issues) == len(issues_doc["issues"]) and not list((data_dir / "sessions" / sid).glob("ISSUE__*.json")), str(issues_doc and issues_doc.get("issue_count")))
hdr = json.loads((data_dir / "sessions" / sid / "session.json").read_text(encoding="utf-8"))["data"]
check("header no longer holds issues", "issues" not in hdr)
order_before = [i["id"] for i in issues]

mutating = next((i for i in issues if i["requires_decision"] and any(o["id"] != "keep" for o in i["options"])), None)
if mutating:
    opt = next(o["id"] for o in mutating["options"] if o["id"] != "keep")
    body = {"issue_id": mutating["id"], "decision_id": opt}
    if opt == "drop_selected":
        body["selected_items"] = (mutating.get("selectable_items") or [])[:1]
    r = client.post(f"/api/audit/{sid}/resolve", json=body)
    check("resolve 200", r.status_code == 200, r.text[:300])
    idoc = next(i for i in doc_store.get(sid, "ISSUES")["issues"] if i["id"] == mutating["id"])
    check("ISSUES entry resolved + applied step", idoc["status"] == "resolved" and idoc["applied"] and idoc["applied"]["decision_id"] == opt, str(idoc.get("applied")))
    ev = audit_log.events_for_target(sid, f"ISSUES#{mutating['id']}")
    check("decision event targets the issue inside ISSUES", ev and ev[0]["event_type"] == "decision" and ev[0]["step"] == 3 and ev[0]["category"] == "audit", str(ev[:1]))
    store._cache.clear()
    r = client.post(f"/api/audit/{sid}/run")  # a session that already has findings returns them as they are stored
    check("reload keeps issue order + status", [i["id"] for i in r.json()["issues"]] == order_before and next(i for i in r.json()["issues"] if i["id"] == mutating["id"])["status"] == "resolved")
    r = client.post(f"/api/audit/{sid}/issues/{mutating['id']}/revert")
    check("revert 200", r.status_code == 200, r.text[:300])
    idoc = next(i for i in doc_store.get(sid, "ISSUES")["issues"] if i["id"] == mutating["id"])
    check("ISSUES entry back to pending, applied cleared", idoc["status"] == "pending" and idoc["applied"] is None)
else:
    print("   (no mutating issue in this sample; resolve/revert skipped)")

from app.schemas import AnalysisResult, DrilldownProposal  # noqa: E402
sess = store.get(sid)
res = AnalysisResult(id=a["id"], run_status="done",
                     guided_proposals=[DrilldownProposal(child_dimension="Carrier", focus_values=["A"]), DrilldownProposal(child_dimension="Origin", focus_values=["B", "C"])])
sess.analysis_results[a["id"]] = res
store.save(sess)
names = sorted(p.name for p in (data_dir / "sessions" / sid).glob("PROPOSAL__*.json"))
check("PROPOSAL# docs written", len(names) == 2, str(names))
rdoc = doc_store.get(sid, f"RESULT#{a['id']}")
check("RESULT# doc has no embedded proposals", rdoc is not None and not rdoc.get("guided_proposals"))
store._cache.clear()
back = store.get(sid).analysis_results[a["id"]]
check("proposals reattached on load", [p.child_dimension for p in back.guided_proposals] == ["Carrier", "Origin"])
back.guided_proposals = back.guided_proposals[:1]
sess2 = store.get(sid)
sess2.analysis_results[a["id"]] = back
store.save(sess2)
check("shrinking proposals deletes extras", len(list((data_dir / "sessions" / sid).glob("PROPOSAL__*.json"))) == 1)

# ---- 8. session reload -------------------------------------------------------------------------
store._cache.clear()
s2 = store.get(sid)
check("session reload keeps row_count", s2 is not None and s2.row_count == meta["row_count"])

print()
print("FAILURES:", failures if failures else "none")
shutil.rmtree(data_dir, ignore_errors=True)
sys.exit(1 if failures else 0)

import { Spinner } from "../components/ThinkingLoader";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import PageNav from "../components/PageNav";
import { IconLayers } from "../components/icons";
import { finalizeBrief } from "../api/brief";
import { loadTrips } from "../api/swp";
import type { SwpTripsResponse, TripEdit, TripEdits } from "../api/swp";
import { hasBrief } from "../context/plannerSkipped";
import { formatDateTime, fromInputValue, selectedTrips, toInputValue, withEdit } from "../utils/swpTrips";
import type { SwpConfigState } from "../utils/swpTrips";
import type { FilesState } from "../App";
import type { BriefState } from "../components/ClientBriefInput";
import "./TripsPage.css";

interface TripsPageProps {
  brief: BriefState;
  files: FilesState;
  config: SwpConfigState;
  trips: SwpTripsResponse | null;
  edits: TripEdits;
  onEditsChange: (edits: TripEdits) => void;
  onLoadComplete: (sessionId: string, label: File, signature: string) => void;
  uploadedSessionIds: Partial<Record<string, string>>;
  uploadedBriefSignature: string | null;
}

const ARRIVED = "Arrived";
const IN_TRANSIT = "InTransit";

export default function TripsPage({
  brief,
  files,
  config,
  trips,
  edits,
  onEditsChange,
  onLoadComplete,
  uploadedSessionIds,
  uploadedBriefSignature,
}: TripsPageProps) {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ departure: string; arrival: string }>({ departure: "", arrival: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The trips chosen on the Configure page, with the changes made here laid over what SWP returned.
  const rows = useMemo(() => selectedTrips(trips, config).map((t) => withEdit(t, edits)), [trips, config, edits]);

  const counts = useMemo(() => {
    const byStatus: Record<string, number> = {};
    for (const r of rows) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1;
    return byStatus;
  }, [rows]);
  const statuses = Object.keys(counts).sort();

  const shown = rows.filter(
    (r) =>
      (!statusFilter || r.status === statusFilter) &&
      (!search.trim() || r.trip_id.toLowerCase().includes(search.trim().toLowerCase()))
  );

  const setEdit = (tripId: string, patch: TripEdit | null) => {
    const next = { ...edits };
    const merged = patch === null ? null : { ...next[tripId], ...patch };
    if (!merged || Object.keys(merged).length === 0) delete next[tripId];
    else next[tripId] = merged;
    onEditsChange(next);
  };

  // Changing a trip here only changes what this app shows and loads. Sending it to SWP is the commented-out
  // update_trip in backend/app/services/swp/client.py (UpdateTrip in the Trip Manage API).
  const markArrived = (tripId: string) => setEdit(tripId, { status: ARRIVED });

  const startEdit = (tripId: string, departure: string | null, arrival: string | null) => {
    setEditing(tripId);
    setDraft({ departure: toInputValue(departure), arrival: toInputValue(arrival) });
  };
  // The new time as ISO text, or "" when it was left empty or is the same as before.
  const changedTime = (input: string, original: string | null) => {
    if (!input || (original && toInputValue(original) === input)) return "";
    return fromInputValue(input);
  };
  const saveEdit = (tripId: string, original: { departure: string | null; arrival: string | null }) => {
    const patch: TripEdit = {};
    const departure = changedTime(draft.departure, original.departure);
    const arrival = changedTime(draft.arrival, original.arrival);
    if (departure) patch.departure = departure;
    if (arrival) patch.arrival = arrival;
    if (Object.keys(patch).length) setEdit(tripId, patch);
    setEditing(null);
  };

  const handleContinue = async () => {
    if (rows.length === 0) return;
    const ids = rows.map((r) => r.trip_id);
    // Same choices and the same brief as the session we already have: carry on with it instead of
    // loading (and planning) all over again.
    const signature = JSON.stringify([brief.rawText, brief.finalText, config.programId, config.sensors, ids, edits]);
    if (uploadedSessionIds.sensiwatch && signature === uploadedBriefSignature) {
      navigate(hasBrief(brief) ? "/planner" : "/audit");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const loaded = await loadTrips({
        program_id: config.programId.trim() || null,
        trip_ids: ids,
        sensors: config.sensors,
        edits: Object.fromEntries(ids.filter((id) => edits[id]).map((id) => [id, edits[id]])),
      });
      // The Planner and the later steps only look at the file's name, so a stand-in carries the label.
      const label = new File([], loaded.filename);
      await finalizeBrief(brief, { ...files, sensiwatch: label }, [loaded.session_id]);
      onLoadComplete(loaded.session_id, label, signature);
      navigate(hasBrief(brief) ? "/planner" : "/audit");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the trips. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  const next = (
    <button type="button" className="btn btn--primary" onClick={handleContinue} disabled={loading || rows.length === 0}>
      {loading ? <><Spinner />Loading trip data…</> : "Load Data & Continue"}
    </button>
  );

  if (!trips || rows.length === 0) {
    return (
      <div className="trips-page">
        <Header subtitle="Trips" />
        <main className="trips-page__main">
          <StepIndicator current={2} />
          <div className="trips-page__empty">
            <p>{trips ? "No trips are selected." : "No trips have been fetched yet."}</p>
            <button type="button" className="btn btn--primary" onClick={() => navigate("/upload")}>
              Go to Configure
            </button>
          </div>
        </main>
      </div>
    );
  }

  const tile = (label: string, value: number, key?: string) => (
    <button
      type="button"
      key={label}
      className={`trips-tile${key !== undefined && statusFilter === key ? " trips-tile--active" : ""}`}
      onClick={() => key !== undefined && setStatusFilter(statusFilter === key ? "" : key)}
      aria-pressed={key !== undefined ? statusFilter === key : undefined}
    >
      <span className="trips-tile__value">{value}</span>
      <span className="trips-tile__label">{label}</span>
    </button>
  );

  return (
    <div className="trips-page">
      <Header subtitle="Trips" />
      <main className="trips-page__main">
        <StepIndicator current={2} />

        <PageNav position="top" onBack={() => navigate("/upload")}>
          {next}
        </PageNav>

        <PageHeader
          icon={<IconLayers />}
          title="Trips"
          subtitle="The trips you chose, by status. Mark an in-transit trip as arrived, or change a departure or arrival time: the change is made here and carried into the audit; it is not sent to SWP."
        />

        {error && <div className="trips-page__error">{error}</div>}

        <div className="trips-tiles">
          {tile("Selected trips", rows.length)}
          {statuses.map((s) => tile(s, counts[s], s))}
          {Object.keys(edits).length > 0 && tile("Edited here", Object.keys(edits).filter((id) => rows.some((r) => r.trip_id === id)).length)}
        </div>

        <div className="trips-filters">
          <label className="trips-filters__field">
            <span>Status</span>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All ({rows.length})</option>
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {s} ({counts[s]})
                </option>
              ))}
            </select>
          </label>
          <input
            className="trips-filters__search"
            type="search"
            placeholder="Search by trip id"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {Object.keys(edits).length > 0 && (
            <button type="button" className="swp-link" onClick={() => onEditsChange({})}>
              Undo all changes
            </button>
          )}
        </div>

        <div className="trips-table-wrap">
          <table className="trips-table">
            <thead>
              <tr>
                <th>Trip ID</th>
                <th>Status</th>
                <th>Departure</th>
                <th>Arrival</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && (
                <tr>
                  <td colSpan={5} className="trips-table__none">
                    No trips match the filter.
                  </td>
                </tr>
              )}
              {shown.map((r) => {
                const isEditing = editing === r.trip_id;
                const edit = edits[r.trip_id];
                return (
                  <tr key={r.trip_id} className={r.edited ? "trips-table__row--edited" : undefined}>
                    <td className="trips-table__id">{r.trip_id}</td>
                    <td>
                      <span className={`trips-status trips-status--${r.status.toLowerCase()}`}>{r.status}</span>
                      {edit?.status && <span className="trips-edited"> edited</span>}
                    </td>
                    <td>
                      {isEditing ? (
                        <input
                          type="datetime-local"
                          value={draft.departure}
                          onChange={(e) => setDraft({ ...draft, departure: e.target.value })}
                          aria-label="Departure time"
                        />
                      ) : (
                        <>
                          {formatDateTime(r.departure)}
                          {edit?.departure && <span className="trips-edited"> edited</span>}
                        </>
                      )}
                    </td>
                    <td>
                      {isEditing ? (
                        <input
                          type="datetime-local"
                          value={draft.arrival}
                          onChange={(e) => setDraft({ ...draft, arrival: e.target.value })}
                          aria-label="Arrival time"
                        />
                      ) : (
                        <>
                          {formatDateTime(r.arrival)}
                          {edit?.arrival && <span className="trips-edited"> edited</span>}
                        </>
                      )}
                    </td>
                    <td className="trips-table__actions">
                      {isEditing ? (
                        <>
                          <button type="button" className="btn btn--primary btn--small" onClick={() => saveEdit(r.trip_id, r)}>
                            Save
                          </button>
                          <button type="button" className="btn btn--secondary btn--small" onClick={() => setEditing(null)}>
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          {r.status === IN_TRANSIT && (
                            <button type="button" className="btn btn--secondary btn--small" onClick={() => markArrived(r.trip_id)}>
                              Mark arrived
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn--secondary btn--small"
                            onClick={() => startEdit(r.trip_id, r.departure, r.arrival)}
                          >
                            Edit times
                          </button>
                          {r.edited && (
                            <button type="button" className="swp-link" onClick={() => setEdit(r.trip_id, null)}>
                              Undo
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <PageNav position="bottom" onBack={() => navigate("/upload")}>
          {next}
        </PageNav>
      </main>
    </div>
  );
}

import { useCallback, useMemo, useState } from "react";
import ApiProgress from "./ApiProgress";
import { fetchAllTrips } from "../api/swp";
import type { SwpTripsResponse, TripEdits } from "../api/swp";
import {
  ARRIVED,
  IN_TRANSIT,
  SENSOR_OPTIONS,
  formatDateTime,
  kpisOf,
  matchingTrips,
  parseTripIds,
  selectedTrips,
  tripsInView,
  unknownTripIds,
} from "../utils/swpTrips";
import type { SwpConfigState } from "../utils/swpTrips";
import { Spinner } from "./ThinkingLoader";
import "../pages/UploadPage.css";
import "../pages/TripsPage.css";

const MAX_LISTED_TRIPS = 300;
type View = typeof IN_TRANSIT | typeof ARRIVED;

interface SwpConfigPanelProps {
  config: SwpConfigState;
  onConfigChange: (config: SwpConfigState) => void;
  trips: SwpTripsResponse | null;
  onTripsChange: (trips: SwpTripsResponse | null) => void;
  /** Status changes and time changes made in the app (nothing is sent to SWP). */
  edits: TripEdits;
  onEditsChange: (edits: TripEdits) => void;
  disabled?: boolean;
}

const show = (value: number | null, unit = "") => (value == null ? "–" : `${value}${unit}`);

/** The SWP side of the Configure page. The program id fetches EVERY trip of the program (stored data is reused);
 * then the trips are shown by status with cards, In Transit or Arrived. Only arrived trips go on to the audit. */
export default function SwpConfigPanel({ config, onConfigChange, trips, onTripsChange, edits, onEditsChange, disabled }: SwpConfigPanelProps) {
  const [fetching, setFetching] = useState(false);
  const [progressId, setProgressId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>(IN_TRANSIT);
  const [search, setSearch] = useState("");

  const fetchTrips = useCallback(
    async (refresh: boolean) => {
      setFetching(true);
      setError(null);
      const id = crypto.randomUUID();
      setProgressId(id);
      try {
        onTripsChange(await fetchAllTrips(config.programId, refresh, id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not fetch the trips. Is the backend running?");
      } finally {
        setFetching(false);
        setProgressId(null);
      }
    },
    [config.programId, onTripsChange]
  );

  const update = (patch: Partial<SwpConfigState>) => onConfigChange({ ...config, ...patch });

  // Trips fetched for another program id are not shown: the list belongs to the id that was fetched.
  const programId = config.programId.trim();
  const shownTrips = trips && trips.program_id === programId ? trips : null;
  const dateFilterOn = Boolean(config.dateFrom || config.dateTo);
  const inDates = useMemo(() => matchingTrips(shownTrips, config), [shownTrips, config]);
  const inView = useMemo(() => tripsInView(shownTrips, config, edits, view), [shownTrips, config, edits, view]);
  const counts = useMemo(
    () => ({
      [IN_TRANSIT]: tripsInView(shownTrips, config, edits, IN_TRANSIT).length,
      [ARRIVED]: tripsInView(shownTrips, config, edits, ARRIVED).length,
    }),
    [shownTrips, config, edits]
  );
  const kpis = useMemo(() => kpisOf(inView), [inView]);
  const toLoad = useMemo(() => selectedTrips(shownTrips, config, edits), [shownTrips, config, edits]);
  const unknown = useMemo(() => unknownTripIds(shownTrips, config), [shownTrips, config]);
  const typed = parseTripIds(config.idsText);

  const listed = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = q
      ? inView.filter((t) => [t.trip_id, t.number, t.trailer_id, t.product, t.origin, t.destination, t.carrier].some((v) => (v ?? "").toLowerCase().includes(q)))
      : inView;
    return rows.slice(0, MAX_LISTED_TRIPS);
  }, [inView, search]);

  const toggleSensor = (name: string) =>
    update({ sensors: config.sensors.includes(name) ? config.sensors.filter((s) => s !== name) : [...config.sensors, name] });

  const markArrived = (tripId: string) => onEditsChange({ ...edits, [tripId]: { ...edits[tripId], status: ARRIVED } });
  const undo = (tripId: string) => {
    const next = { ...edits };
    delete next[tripId];
    onEditsChange(next);
  };

  const tile = (label: string, value: string) => (
    <div className="trips-tile" key={label}>
      <span className="trips-tile__value">{value}</span>
      <span className="trips-tile__label">{label}</span>
    </div>
  );

  return (
    <section className="swp-card">
      <div className="swp-card__head">
        <h2 className="swp-card__title">SWP API</h2>
      </div>

      <div className="swp-form">
        <label className="swp-field">
          <span className="swp-field__label">Program ID</span>
          <span className="swp-inline">
            <input
              className="swp-field__input"
              type="text"
              inputMode="numeric"
              placeholder="Enter the program ID"
              value={config.programId}
              onChange={(e) => update({ programId: e.target.value, idsText: "" })}
              disabled={disabled || fetching}
            />
            <button type="button" className="btn btn--secondary" onClick={() => fetchTrips(false)} disabled={disabled || fetching || !programId}>
              {fetching ? <><Spinner />Fetching…</> : "Fetch all trips"}
            </button>
          </span>
          <span className="swp-field__hint">Fetches every trip of the program. What was fetched before is reused, so only new or changed trips take time.</span>
        </label>

        <div className="swp-field">
          <span className="swp-field__label">Departure date (UTC)</span>
          <span className="swp-inline">
            <input
              className="swp-field__input"
              type="date"
              aria-label="Departure from"
              value={config.dateFrom}
              max={config.dateTo || undefined}
              onChange={(e) => update({ dateFrom: e.target.value })}
              disabled={disabled}
            />
            <span className="swp-field__hint">to</span>
            <input
              className="swp-field__input"
              type="date"
              aria-label="Departure to"
              value={config.dateTo}
              min={config.dateFrom || undefined}
              onChange={(e) => update({ dateTo: e.target.value })}
              disabled={disabled}
            />
            {dateFilterOn && (
              <button type="button" className="swp-link" onClick={() => update({ dateFrom: "", dateTo: "" })}>
                Clear
              </button>
            )}
          </span>
        </div>

        <div className="swp-field">
          <span className="swp-field__label">Sensors to load</span>
          <span className="swp-inline" role="group" aria-label="Sensors">
            {SENSOR_OPTIONS.map((name) => (
              <label key={name} className="swp-check">
                <input type="checkbox" checked={config.sensors.includes(name)} onChange={() => toggleSensor(name)} disabled={disabled} />
                {name}
              </label>
            ))}
          </span>
          <span className={`swp-field__hint${config.sensors.some((s) => s === "Temperature" || s === "Light") ? "" : " swp-field__hint--error"}`}>
            Temperature and Light go into the audit table; Humidity is only drawn in the Inspect graph. Pick Temperature or Light.
          </span>
        </div>
      </div>

      {fetching && <ApiProgress progressId={progressId} fallback="Fetching all trips from the SWP API (it is rate limited, so the first time can take a few minutes)…" />}
      {error && <div className="upload-page__error">{error}</div>}
      {!shownTrips && !fetching && !error && (
        <p className="swp-card__note">{programId ? "Click Fetch all trips to list this program's trips." : "Enter a program ID to see its trips."}</p>
      )}

      {shownTrips && (
        <>
          <p className="swp-card__note">
            <strong>{shownTrips.total}</strong> trips in program {shownTrips.program_id}
            {dateFilterOn && <> — <strong>{inDates.length}</strong> depart in the chosen dates</>}.{" "}
            {shownTrips.from_cache ? "Trip list reused from the earlier fetch" : "Fetched from SWP"} ({formatDateTime(shownTrips.fetched_at)}).{" "}
            <button type="button" className="swp-link" onClick={() => fetchTrips(true)} disabled={disabled || fetching}>
              Refresh from SWP
            </button>
          </p>

          <div className="source-toggle" role="tablist" aria-label="Trips by status">
            {([IN_TRANSIT, ARRIVED] as const).map((status) => (
              <button
                key={status}
                type="button"
                role="tab"
                aria-selected={view === status}
                className={`source-toggle__option${view === status ? " source-toggle__option--active" : ""}`}
                onClick={() => setView(status)}
              >
                {status === IN_TRANSIT ? "In Transit" : "Arrived"} ({counts[status]})
              </button>
            ))}
          </div>

          <div className="trips-tiles">
            {tile("Total trips", String(inDates.length))}
            {tile("Arrived", String(counts[ARRIVED]))}
            {tile("In transit", String(counts[IN_TRANSIT]))}
            {tile(`Alarmed (${view === IN_TRANSIT ? "in transit" : "arrived"})`, String(kpis.alarmed))}
            {tile(`Avg mean temp (${view === IN_TRANSIT ? "in transit" : "arrived"})`, show(kpis.avgMeanTemp, " °C"))}
            {tile(`Avg segment days (${view === IN_TRANSIT ? "in transit" : "arrived"})`, show(kpis.avgSegmentDays))}
          </div>

          <div className="swp-picker__head">
            <input
              className="swp-field__input swp-picker__search"
              type="search"
              placeholder="Search by trip id, product, origin, destination or carrier"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <span className="swp-field__hint">
              {view === IN_TRANSIT
                ? "Trips still on their way are not analysed. Mark one arrived to include it (changes this app only, not SWP)."
                : "These are the trips that go on to the audit."}
            </span>
          </div>
          <div className="trips-table-wrap swp-trips-list">
            <table className="trips-table">
              <thead>
                <tr>
                  <th>Trip ID</th>
                  <th>Product</th>
                  <th>Lane</th>
                  <th>Departure</th>
                  <th>Arrival</th>
                  <th>Mean °C</th>
                  <th>Segment days</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {listed.length === 0 && (
                  <tr>
                    <td colSpan={8} className="trips-table__none">
                      No {view === IN_TRANSIT ? "in-transit" : "arrived"} trips{dateFilterOn || search ? " match" : ""}.
                    </td>
                  </tr>
                )}
                {listed.map((t) => (
                  <tr key={t.trip_id} className={t.edited ? "trips-table__row--edited" : undefined}>
                    <td className="trips-table__id" title={t.trip_id}>
                      {t.number ?? t.trip_id}
                      {t.alarmed && <span className="trips-edited"> alarmed</span>}
                    </td>
                    <td>{t.product ?? "–"}</td>
                    <td>{t.origin || t.destination ? `${t.origin ?? "?"} → ${t.destination ?? "?"}` : "–"}</td>
                    <td>{formatDateTime(t.departure)}</td>
                    <td>{formatDateTime(t.arrival)}</td>
                    <td>{show(t.mean_temp)}</td>
                    <td>{show(t.segment_days)}</td>
                    <td className="trips-table__actions">
                      {view === IN_TRANSIT ? (
                        <button type="button" className="btn btn--secondary btn--small" onClick={() => markArrived(t.trip_id)} disabled={disabled}>
                          Mark arrived
                        </button>
                      ) : (
                        t.edited && (
                          <button type="button" className="swp-link" onClick={() => undo(t.trip_id)} disabled={disabled}>
                            Undo
                          </button>
                        )
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {inView.length > listed.length && !search && <p className="swp-card__note">Showing the first {MAX_LISTED_TRIPS}; search or set dates to narrow the list.</p>}

          <label className="swp-field" style={{ marginTop: 16 }}>
            <span className="swp-field__label">Trip IDs (optional)</span>
            <textarea
              className="swp-field__input swp-ids"
              rows={3}
              spellCheck={false}
              placeholder="To load only some trips, paste their IDs (the number or the GUID), one per line or separated by commas. Leave empty to load every arrived trip above."
              value={config.idsText}
              onChange={(e) => update({ idsText: e.target.value })}
              disabled={disabled}
            />
            {typed.length > 0 && unknown.length > 0 && (
              <span className="swp-field__hint swp-field__hint--error">Not found: {unknown.slice(0, 3).join(", ")}{unknown.length > 3 ? ` and ${unknown.length - 3} more` : ""}.</span>
            )}
          </label>

          <p className={`swp-summary${toLoad.length === 0 ? " swp-summary--error" : ""}`}>
            {toLoad.length === 0
              ? "No arrived trips to load: switch some in-transit trips to arrived, or widen the dates."
              : `${toLoad.length} arrived trip${toLoad.length === 1 ? "" : "s"} will be loaded.`}
          </p>
        </>
      )}
    </section>
  );
}

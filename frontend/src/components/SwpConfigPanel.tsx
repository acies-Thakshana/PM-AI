import { useCallback, useEffect, useMemo, useState } from "react";
import ApiProgress from "./ApiProgress";
import ExcelTable from "./ExcelTable";
import { fetchAggregate, fetchAllTrips, startPrefetch } from "../api/swp";
import type { SwpAggregate, SwpPrefetchStatus, SwpTripsResponse, TripEdits } from "../api/swp";
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
import { IconDownload, IconSnowflake } from "./icons";
import "../pages/UploadPage.css";
import "../pages/TripsPage.css";

const MAX_LISTED_TRIPS = 300;
const AGGREGATE = "Aggregate";
type View = typeof IN_TRANSIT | typeof ARRIVED | typeof AGGREGATE;

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

function formatWait(seconds: number): string {
  if (seconds < 60) return `${Math.max(Math.round(seconds), 1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
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
  const [prefetch, setPrefetch] = useState<SwpPrefetchStatus | null>(null);
  const [retry, setRetry] = useState(0);
  const [aggregate, setAggregate] = useState<SwpAggregate | null>(null);
  const [aggregateError, setAggregateError] = useState<string | null>(null);

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
  // The Aggregate tab shows the table of the arrived trips; the cards and search below it belong to the arrived list.
  const listView = view === AGGREGATE ? ARRIVED : view;
  const inView = useMemo(() => tripsInView(shownTrips, config, edits, listView), [shownTrips, config, edits, listView]);
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

  // As soon as the trip list is here, the arrived trips that will be analysed have their details (call 4) fetched in the
  // background. Sending the same ids again only reports the progress, so this loop is also the poll.
  const idsKey = toLoad.map((t) => t.trip_id).join(",");
  const prefetchProgram = shownTrips?.program_id;
  useEffect(() => {
    if (!prefetchProgram || !idsKey) {
      setPrefetch(null);
      return;
    }
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const status = await startPrefetch(prefetchProgram, idsKey.split(","));
        if (!live) return;
        setPrefetch(status);
        if (status.running) timer = setTimeout(tick, 2000);
      } catch (err) {
        if (live) setPrefetch({ total: 0, done: 0, failed: 0, running: false, error: err instanceof Error ? err.message : "Could not fetch the trip details.", seconds_per_trip: 0 });
      }
    };
    const start = setTimeout(tick, 400); // wait a moment: marking trips arrived changes the list several times in a row
    return () => {
      live = false;
      clearTimeout(start);
      if (timer) clearTimeout(timer);
    };
  }, [prefetchProgram, idsKey, retry]);

  const sensorsKey = config.sensors.join(",");
  const editsKey = JSON.stringify(edits);
  const prefetchDone = prefetch?.done ?? 0;
  const prefetchRunning = prefetch?.running ?? false;
  const prefetchTotal = prefetch?.total ?? -1;
  useEffect(() => {
    if (!prefetchProgram || !idsKey) {
      setAggregate(null);
      return;
    }
    // built when the tab is open (so it fills up as details arrive), and once when everything is ready (which also writes the Excel)
    if (view !== AGGREGATE && !(!prefetchRunning && prefetchDone === prefetchTotal)) return;
    let live = true;
    const ids = idsKey.split(",");
    const handle = setTimeout(async () => {
      try {
        const result = await fetchAggregate({
          program_id: prefetchProgram,
          trip_ids: ids,
          sensors: sensorsKey ? sensorsKey.split(",") : [],
          edits: Object.fromEntries(ids.filter((id) => edits[id]).map((id) => [id, edits[id]])),
        });
        if (live) {
          setAggregate(result);
          setAggregateError(null);
        }
      } catch (err) {
        if (live) setAggregateError(err instanceof Error ? err.message : "Could not build the aggregate table.");
      }
    }, 800);
    return () => {
      live = false;
      clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, prefetchProgram, idsKey, sensorsKey, editsKey, prefetchDone, prefetchRunning, prefetchTotal]);

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
        <span className="swp-card__badge" aria-hidden="true">
          <IconSnowflake />
        </span>
        <div>
          <h2 className="swp-card__title">SWP API</h2>
          <p className="swp-card__sub">Pull a program's trips straight from SensiWatch. Nothing is written back.</p>
        </div>
      </div>

      <div className="swp-form">
        <div className="swp-field">
          <label className="swp-field__label" htmlFor="swp-program-id">
            <span className="swp-step">1</span> Program ID
          </label>
          <input
            id="swp-program-id"
            className="swp-field__input"
            type="text"
            inputMode="numeric"
            placeholder="e.g. 651"
            value={config.programId}
            onChange={(e) => update({ programId: e.target.value, idsText: "" })}
            onKeyDown={(e) => {
              if (e.key === "Enter" && programId && !disabled && !fetching) void fetchTrips(false);
            }}
            disabled={disabled || fetching}
          />
          <span className="swp-field__hint">The program whose trips you want to work with.</span>
        </div>

        <div className="swp-field">
          <span className="swp-field__label">
            <span className="swp-step">2</span> Departure date (UTC) <span className="swp-optional">Optional</span>
          </span>
          <span className="swp-dates">
            <input
              className="swp-field__input"
              type="date"
              aria-label="Departure from"
              value={config.dateFrom}
              max={config.dateTo || undefined}
              onChange={(e) => update({ dateFrom: e.target.value })}
              disabled={disabled}
            />
            <span className="swp-dates__to" aria-hidden="true">
              to
            </span>
            <input
              className="swp-field__input"
              type="date"
              aria-label="Departure to"
              value={config.dateTo}
              min={config.dateFrom || undefined}
              onChange={(e) => update({ dateTo: e.target.value })}
              disabled={disabled}
            />
          </span>
          <span className="swp-field__hint">
            Only trips that left in this window are used.
            {dateFilterOn && (
              <>
                {" "}
                <button type="button" className="swp-link" onClick={() => update({ dateFrom: "", dateTo: "" })}>
                  Clear dates
                </button>
              </>
            )}
          </span>
        </div>

        <div className="swp-field">
          <span className="swp-field__label">
            <span className="swp-step">3</span> Sensors to load
          </span>
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

      <div className="swp-fetchbar">
        <p className="swp-fetchbar__hint">
          Fetches the list of every trip of the program (quick). The details of the arrived trips are then fetched in the background.
        </p>
        <button type="button" className="swp-fetch" onClick={() => fetchTrips(false)} disabled={disabled || fetching || !programId}>
          {fetching ? (
            <>
              <Spinner />
              Fetching…
            </>
          ) : (
            <>
              <IconDownload />
              Fetch all trips
            </>
          )}
        </button>
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
            {([IN_TRANSIT, ARRIVED, AGGREGATE] as const).map((status) => (
              <button
                key={status}
                type="button"
                role="tab"
                aria-selected={view === status}
                className={`source-toggle__option${view === status ? " source-toggle__option--active" : ""}`}
                onClick={() => setView(status)}
              >
                {status === AGGREGATE ? "Aggregate data (Excel view)" : `${status === IN_TRANSIT ? "In Transit" : "Arrived"} (${counts[status]})`}
              </button>
            ))}
          </div>

          <div className="trips-tiles">
            {tile("Total trips", String(inDates.length))}
            {tile("Arrived", String(counts[ARRIVED]))}
            {tile("In transit", String(counts[IN_TRANSIT]))}
            {tile(`Alarmed (${listView === IN_TRANSIT ? "in transit" : "arrived"})`, String(kpis.alarmed))}
            {tile(`Avg mean temp (${listView === IN_TRANSIT ? "in transit" : "arrived"})`, show(kpis.avgMeanTemp, " °C"))}
            {tile(`Avg segment days (${listView === IN_TRANSIT ? "in transit" : "arrived"})`, show(kpis.avgSegmentDays))}
          </div>

          {view !== AGGREGATE && (
          <>
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
          </>
          )}

          {view === AGGREGATE && (
            <div>
              <p className="swp-card__note">
                The aggregate data: the columns of the Excel file for the {toLoad.length} arrived trips that will be loaded. Rows marked <strong>search</strong> come
                from the trip search (SWP's own statistics, shown at once); each switches to <strong>detail</strong>, with every column filled, when that trip's details have been fetched.{" "}
                {aggregate
                  ? `${aggregate.trips_ready} of ${aggregate.trips_total} trips are complete.`
                  : "Building the table…"}
                {aggregate?.saved_to && <> Saved as Excel: <code>{aggregate.saved_to}</code></>}
              </p>
              {aggregateError && <div className="upload-page__error">{aggregateError}</div>}
              {aggregate &&
                (aggregate.rows.length > 0 ? (
                  <div className="swp-aggregate">
                    <ExcelTable columns={aggregate.columns} rows={aggregate.rows} frozen={["Serial Number", "Trip ID"]} />
                  </div>
                ) : (
                  <p className="swp-card__note">No trip details have arrived yet; the first rows appear in a few seconds.</p>
                ))}
            </div>
          )}

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

          {prefetch && toLoad.length > 0 && (
            <div className="api-progress" role="status" aria-live="polite">
              <div className="api-progress__text">
                {prefetch.error && !prefetch.running ? (
                  <>
                    Could not fetch {prefetch.failed || "some"} trip detail(s): {prefetch.error}{" "}
                    <button type="button" className="swp-link" onClick={() => setRetry((n) => n + 1)}>Try again</button>
                  </>
                ) : prefetch.running ? (
                  <>
                    Fetching the details of the arrived trips in the background: <strong>{prefetch.done} / {prefetch.total}</strong>
                    {" "}(about {formatWait(Math.max(prefetch.total - prefetch.done - prefetch.failed, 0) * prefetch.seconds_per_trip)} left). You can carry on.
                  </>
                ) : (
                  <>Trip details ready: <strong>{prefetch.done} / {prefetch.total}</strong> arrived trips. Continuing will be quick.</>
                )}
              </div>
              <div className="api-progress__bar" aria-hidden="true">
                <div className="api-progress__fill" style={{ width: `${prefetch.total ? Math.round((prefetch.done / prefetch.total) * 100) : 0}%` }} />
              </div>
            </div>
          )}

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

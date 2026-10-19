import { useCallback, useMemo, useState } from "react";
import ApiProgress from "./ApiProgress";
import { fetchAllTrips } from "../api/swp";
import type { SwpTripsResponse } from "../api/swp";
import { SENSOR_OPTIONS, formatDateTime, matchingTrips, parseTripIds, selectedTrips, unknownTripIds } from "../utils/swpTrips";
import type { SwpConfigState } from "../utils/swpTrips";
import { Spinner } from "./ThinkingLoader";
import "../pages/UploadPage.css";

const MAX_LISTED_TRIPS = 300;

interface SwpConfigPanelProps {
  config: SwpConfigState;
  onConfigChange: (config: SwpConfigState) => void;
  trips: SwpTripsResponse | null;
  onTripsChange: (trips: SwpTripsResponse | null) => void;
  disabled?: boolean;
}

/** The SWP side of the Configure page: the program id, which departure dates and sensors, then (once the
 * program's trips have been fetched) a box for the trip IDs to load and the trips departing in the dates,
 * with their ids and departure dates. */
export default function SwpConfigPanel({ config, onConfigChange, trips, onTripsChange, disabled }: SwpConfigPanelProps) {
  const [fetching, setFetching] = useState(false);
  const [progressId, setProgressId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
  const matches = useMemo(() => matchingTrips(shownTrips, config), [shownTrips, config]);
  const chosen = useMemo(() => selectedTrips(shownTrips, config), [shownTrips, config]);
  const unknown = useMemo(() => unknownTripIds(shownTrips, config), [shownTrips, config]);
  const typed = parseTripIds(config.idsText);
  const max = shownTrips?.max_trips ?? 1;
  const withDeparture = (shownTrips?.trips ?? []).filter((t) => t.departure).length;
  const dateFilterOn = Boolean(config.dateFrom || config.dateTo);

  const listed = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = q ? matches.filter((t) => [t.trip_id, t.trailer_id, t.status].some((v) => (v ?? "").toLowerCase().includes(q))) : matches;
    return rows.slice(0, MAX_LISTED_TRIPS);
  }, [matches, search]);

  const addId = (id: string) => {
    if (typed.some((t) => t.toLowerCase() === id.toLowerCase())) return;
    update({ idsText: config.idsText.trim() ? `${config.idsText.trim()}\n${id}` : id });
  };
  const toggleSensor = (name: string) =>
    update({ sensors: config.sensors.includes(name) ? config.sensors.filter((s) => s !== name) : [...config.sensors, name] });

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
              {fetching ? <><Spinner />Fetching…</> : "Fetch trips"}
            </button>
          </span>
          <span className="swp-field__hint">Enter the program ID, then fetch: its trip ids and departure dates are listed below.</span>
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
          {config.sensors.length === 0 && <span className="swp-field__hint swp-field__hint--error">Pick at least one sensor.</span>}
        </div>
      </div>

      {fetching && <ApiProgress progressId={progressId} fallback="Fetching all trips from the SWP API (it is rate limited, so this can take a minute)…" />}
      {error && <div className="upload-page__error">{error}</div>}
      {!shownTrips && !fetching && !error && (
        <p className="swp-card__note">{programId ? "Click Fetch trips to list this program's trips." : "Enter a program ID to see its trips."}</p>
      )}

      {shownTrips && (
        <>
          <p className="swp-card__note">
            <strong>{shownTrips.total}</strong> trips in program {shownTrips.program_id}
            {shownTrips.total > 0 && <> — {withDeparture} with a departure date</>}.
            {dateFilterOn && <> <strong>{matches.length}</strong> depart in the chosen dates.</>}
            {" "}
            {shownTrips.from_cache ? "Reused from the earlier fetch" : "Fetched from SWP"} ({formatDateTime(shownTrips.fetched_at)}).{" "}
            <button type="button" className="swp-link" onClick={() => fetchTrips(true)} disabled={disabled || fetching}>
              Refresh from SWP
            </button>
          </p>
          {shownTrips.total > 0 && withDeparture === 0 && (
            <div className="upload-page__error">
              The trip list has no departure date, so the date filter cannot place any trip. Fields in the list:{" "}
              {shownTrips.sample_fields.join(", ")}.
            </div>
          )}

          <label className="swp-field">
            <span className="swp-field__label">Trip IDs</span>
            <textarea
              className="swp-field__input swp-ids"
              rows={4}
              spellCheck={false}
              placeholder="Paste trip IDs, one per line or separated by commas. Leave empty to load the newest trips departing in the dates above."
              value={config.idsText}
              onChange={(e) => update({ idsText: e.target.value })}
              disabled={disabled}
            />
            <span className={`swp-field__hint${unknown.length || chosen.length > max ? " swp-field__hint--error" : ""}`}>
              {typed.length > 0
                ? `${typed.length} ID${typed.length === 1 ? "" : "s"} entered, ${chosen.length} found in this program.${
                    unknown.length ? ` Not found: ${unknown.slice(0, 3).join(", ")}${unknown.length > 3 ? ` and ${unknown.length - 3} more` : ""}.` : ""
                  }`
                : `No IDs entered: the newest ${Math.min(max, matches.length)} trip(s) departing in the dates will be loaded (up to ${max}).`}
              {chosen.length > max && ` At most ${max} trips can be loaded at once.`}
              {typed.length > 0 && (
                <>
                  {" · "}
                  <button type="button" className="swp-link" onClick={() => update({ idsText: "" })}>
                    Clear
                  </button>
                </>
              )}
            </span>
          </label>

          <div className="swp-picker">
            <div className="swp-picker__head">
              <span className="swp-field__label">Trips{dateFilterOn ? " departing in the chosen dates" : ""}</span>
              <input
                className="swp-field__input swp-picker__search"
                type="search"
                placeholder="Search by trip id, trailer or status"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <span className="swp-field__hint">Click a trip id to add it to the box above.</span>
            </div>
            <div className="swp-picker__list" role="list" aria-label="Trips">
              {listed.length === 0 && <p className="swp-card__note">No trips match.</p>}
              {listed.map((t) => (
                <button
                  key={t.trip_id}
                  type="button"
                  role="listitem"
                  className="swp-picker__row swp-picker__row--button"
                  onClick={() => addId(t.trip_id)}
                  disabled={disabled}
                >
                  <span className="swp-picker__id">{t.trip_id}</span>
                  <span className="swp-picker__status">{t.status}</span>
                  <span className="swp-picker__meta">Departs {formatDateTime(t.departure)}</span>
                </button>
              ))}
              {matches.length > listed.length && !search && (
                <p className="swp-card__note">Showing the first {MAX_LISTED_TRIPS}; search or set dates to narrow the list.</p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

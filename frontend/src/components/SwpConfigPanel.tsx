import { useCallback, useEffect, useMemo, useState } from "react";
import { Spinner } from "./ThinkingLoader";
import { fetchAllTrips } from "../api/swp";
import type { SwpTripsResponse } from "../api/swp";
import { SENSOR_OPTIONS, formatDateTime, matchingTrips, selectedTrips } from "../utils/swpTrips";
import type { SwpConfigState } from "../utils/swpTrips";
import "../pages/UploadPage.css";

const MAX_LISTED_TRIPS = 300;

interface SwpConfigPanelProps {
  config: SwpConfigState;
  onConfigChange: (config: SwpConfigState) => void;
  trips: SwpTripsResponse | null;
  onTripsChange: (trips: SwpTripsResponse | null) => void;
  disabled?: boolean;
}

/** The SWP side of the Configure page: which program, which departure dates, which sensors, then the
 * matching trips (id and departure date) to tick. All trips of the program are fetched first. */
export default function SwpConfigPanel({ config, onConfigChange, trips, onTripsChange, disabled }: SwpConfigPanelProps) {
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const fetchTrips = useCallback(
    async (refresh: boolean) => {
      setFetching(true);
      setError(null);
      try {
        onTripsChange(await fetchAllTrips(config.programId, refresh));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not fetch the trips. Is the backend running?");
      } finally {
        setFetching(false);
      }
    },
    [config.programId, onTripsChange]
  );

  // Step 1 happens as soon as the page opens, with the default program, so the options below are real.
  useEffect(() => {
    if (!trips) void fetchTrips(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = (patch: Partial<SwpConfigState>) => onConfigChange({ ...config, ...patch });

  const matches = useMemo(() => matchingTrips(trips, config), [trips, config]);
  const chosen = useMemo(() => selectedTrips(trips, config), [trips, config]);
  const chosenIds = useMemo(() => new Set(chosen.map((t) => t.trip_id)), [chosen]);
  const max = trips?.max_trips ?? 1;
  const withDeparture = (trips?.trips ?? []).filter((t) => t.departure).length;
  const dateFilterOn = Boolean(config.dateFrom || config.dateTo);

  const listed = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = q ? matches.filter((t) => [t.trip_id, t.trailer_id, t.status].some((v) => (v ?? "").toLowerCase().includes(q))) : matches;
    return rows.slice(0, MAX_LISTED_TRIPS);
  }, [matches, search]);

  const toggleTrip = (id: string) => {
    const next = new Set(chosenIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    update({ selectedIds: [...next] });
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
              placeholder={trips ? `Default: ${trips.program_id}` : "Default from the backend settings"}
              value={config.programId}
              onChange={(e) => update({ programId: e.target.value, selectedIds: null })}
              disabled={disabled || fetching}
            />
            <button type="button" className="btn btn--secondary" onClick={() => fetchTrips(true)} disabled={disabled || fetching}>
              {fetching ? <><Spinner />Fetching…</> : "Fetch trips"}
            </button>
          </span>
          <span className="swp-field__hint">Leave empty for the program set in the backend settings.</span>
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
              onChange={(e) => update({ dateFrom: e.target.value, selectedIds: null })}
              disabled={disabled}
            />
            <span className="swp-field__hint">to</span>
            <input
              className="swp-field__input"
              type="date"
              aria-label="Departure to"
              value={config.dateTo}
              min={config.dateFrom || undefined}
              onChange={(e) => update({ dateTo: e.target.value, selectedIds: null })}
              disabled={disabled}
            />
            {dateFilterOn && (
              <button type="button" className="swp-link" onClick={() => update({ dateFrom: "", dateTo: "", selectedIds: null })}>
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

      {fetching && !trips && (
        <p className="swp-card__note">Fetching all trips from the SWP API. This can take a minute (the API is rate limited)…</p>
      )}
      {error && <div className="upload-page__error">{error}</div>}

      {trips && (
        <>
          <p className="swp-card__note">
            <strong>{trips.total}</strong> trips in program {trips.program_id}
            {trips.total > 0 && <> — {withDeparture} with a departure date</>}.
            {dateFilterOn && <> <strong>{matches.length}</strong> depart in the chosen dates.</>}
          </p>
          {trips.total > 0 && withDeparture === 0 && (
            <div className="upload-page__error">
              The trip list has no departure date, so the date filter cannot place any trip. Fields in the list:{" "}
              {trips.sample_fields.join(", ")}.
            </div>
          )}

          <div className="swp-picker">
            <div className="swp-picker__head">
              <span className="swp-field__label">Trips</span>
              <input
                className="swp-field__input swp-picker__search"
                type="search"
                placeholder="Search by trip id, trailer or status"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <span className="swp-field__hint">
                {chosen.length} of {matches.length} selected (up to {max})
                {" · "}
                <button type="button" className="swp-link" onClick={() => update({ selectedIds: null })}>
                  Newest {max}
                </button>
                {" · "}
                <button type="button" className="swp-link" onClick={() => update({ selectedIds: [] })}>
                  None
                </button>
              </span>
            </div>
            <div className="swp-picker__list" role="group" aria-label="Trips">
              {listed.length === 0 && <p className="swp-card__note">No trips match.</p>}
              {listed.map((t) => (
                <label key={t.trip_id} className="swp-picker__row">
                  <input type="checkbox" checked={chosenIds.has(t.trip_id)} onChange={() => toggleTrip(t.trip_id)} disabled={disabled} />
                  <span className="swp-picker__id">{t.trip_id}</span>
                  <span className="swp-picker__status">{t.status}</span>
                  <span className="swp-picker__meta">Departs {formatDateTime(t.departure)}</span>
                </label>
              ))}
              {matches.length > listed.length && !search && (
                <p className="swp-card__note">Showing the first {MAX_LISTED_TRIPS}; search or set dates to narrow the list.</p>
              )}
            </div>
          </div>
          {chosen.length > max && <p className="swp-summary swp-summary--error">At most {max} trips can be loaded at once.</p>}
        </>
      )}
    </section>
  );
}

import { useEffect, useState } from "react";
import { fetchProgress } from "../api/swp";
import type { SwpProgress } from "../api/swp";
import "./ApiProgress.css";

interface ApiProgressProps {
  /** The id sent with the request being waited for; null when nothing is running. */
  progressId: string | null;
  /** Shown before the first answer, and when the request makes no API calls (e.g. it was cached). */
  fallback: string;
}

/** "Loading trip data: 3 / 103 API calls", polled from the backend while a slow SWP request runs. */
export default function ApiProgress({ progressId, fallback }: ApiProgressProps) {
  const [progress, setProgress] = useState<SwpProgress | null>(null);

  useEffect(() => {
    setProgress(null);
    if (!progressId) return;
    let live = true;
    const poll = async () => {
      try {
        const p = await fetchProgress(progressId);
        if (live && p.total > 0) setProgress(p);
      } catch {
        /* a missed poll is fine: the next one will do */
      }
    };
    void poll();
    const timer = setInterval(poll, 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [progressId]);

  if (!progressId) return null;
  const pct = progress && progress.total > 0 ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0;
  return (
    <div className="api-progress" role="status" aria-live="polite">
      <div className="api-progress__text">
        {progress ? (
          <>
            {progress.label || fallback}: <strong>{progress.done} / {progress.total}</strong> API calls
          </>
        ) : (
          fallback
        )}
      </div>
      <div className="api-progress__bar" aria-hidden="true">
        <div className="api-progress__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

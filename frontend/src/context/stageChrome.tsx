import { createContext, useContext, useEffect, useRef } from "react";

export interface StageStat {
  label: string;
  value: string;
  /** A small note after the number, such as a percentage. */
  hint?: string;
}

export interface StageAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  /** Why the action is not available yet, shown next to it. */
  note?: string;
}

/** A quick reply offered above the message box. Choosing it is the PM saying that, in the conversation. */
export interface StageReply {
  label: string;
  onClick: () => void;
  /** The expected next move: drawn filled. */
  main?: boolean;
  disabled?: boolean;
}

/** What a stage page tells the conversation around it: what to say, which numbers to show, and where Back and Next go. */
export interface StageChrome {
  summary?: string;
  stats?: StageStat[];
  back?: StageAction;
  next?: StageAction;
  /** Quick replies for this moment of the conversation. */
  replies?: StageReply[];
  /** Lets the page take the next typed message instead of the assistant. Return true when it was handled. */
  onSend?: (text: string) => boolean;
}

export const StageChromeContext = createContext<(chrome: StageChrome | null) => void>(() => {});

/** Called by a stage page. The callbacks may change on every render; the conversation re-renders only when the
 * text, the numbers or an action's label, state or note change. */
export function useStageChrome(chrome: StageChrome | null) {
  const publish = useContext(StageChromeContext);
  const latest = useRef(chrome);
  latest.current = chrome;

  const key = JSON.stringify(
    chrome && {
      s: chrome.summary,
      t: chrome.stats,
      b: chrome.back && [chrome.back.label, chrome.back.disabled, chrome.back.note],
      n: chrome.next && [chrome.next.label, chrome.next.disabled, chrome.next.note],
      r: chrome.replies?.map((r) => [r.label, r.main, r.disabled]),
      o: !!chrome.onSend,
    }
  );

  useEffect(() => {
    const c = latest.current;
    if (!c) {
      publish(null);
      return;
    }
    publish({
      ...c,
      back: c.back && { ...c.back, onClick: () => latest.current?.back?.onClick() },
      next: c.next && { ...c.next, onClick: () => latest.current?.next?.onClick() },
      replies: c.replies?.map((r, i) => ({ ...r, onClick: () => latest.current?.replies?.[i]?.onClick() })),
      onSend: c.onSend && ((text: string) => latest.current?.onSend?.(text) ?? false),
    });
    return () => publish(null);
  }, [key, publish]);
}

import ThinkingLoader from "../components/ThinkingLoader";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ChatMessage from "../components/ChatMessage";
import ReportChat from "../components/ReportChat";
import type { ReportLogEntry, ReportSlideRow } from "../components/ReportChat";
import { useStageChrome } from "../context/stageChrome";
import type { StageReply } from "../context/stageChrome";
import ReportEditorModal from "../components/ReportEditorModal";
import type { CustomSlide, DeckState, SlideEdit } from "../utils/deck";
import { useStoredRef, useStoredState } from "../state/sessionStore";
import {
  fetchAnalysisRepository,
  fetchReportSummary,
  fetchReportTranslations,
  fetchSupportedReportLanguages,
  AuditApiError,
  exportReport,
  translateTexts,
  type AnalysisRepositoryEntry,
  type EntryTranslation,
  type LanguageOption,
} from "../api/audit";
import { buildReportTree, drilldownSubtitle, isStaleEntry } from "../utils/reportTree";
import { REPORT_CHART_TYPES, type ReportChartType } from "../utils/reportChartTypes";
import { AUDITED_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type RepositoriesState = Partial<Record<UploadSlotId, AnalysisRepositoryEntry[]>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;

function defaultChartType(entry: AnalysisRepositoryEntry): ReportChartType {
  return (REPORT_CHART_TYPES as readonly string[]).includes(entry.chart_type ?? "")
    ? (entry.chart_type as ReportChartType)
    : "bar";
}

// Strips the LLM's boilerplate "The chart shows..." framing and keeps only
// the first couple of sentences -- the PM wants the gist, not a restatement
// of what they're already looking at.
const CHART_LEAD_IN_RE = /^(the|this)\s+(chart|graph|data|visuali[sz]ation)\s+(shows?|illustrates?|indicates?|reveals?|highlights?)\s*(that\s+)?/i;
const MAX_SUMMARY_CHARS = 220;

function shortenInterpretation(text: string): string {
  let s = text.trim().replace(CHART_LEAD_IN_RE, "");
  if (s) s = s[0].toUpperCase() + s.slice(1);
  const sentences = s.split(/(?<=[.!?])\s+/).filter(Boolean);
  let result = sentences.slice(0, 2).join(" ");
  if (result.length > MAX_SUMMARY_CHARS) result = `${result.slice(0, MAX_SUMMARY_CHARS - 1).trimEnd()}…`;
  return result || text;
}

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  // Everything the PM chose (selection, order, language, expanded charts) lives in the
  // shared store so it survives leaving this page; the analysis repository itself is
  // refetched on each visit (stale-while-revalidate) since the Analysis page can change it.
  const [repositories, setRepositories] = useStoredState<RepositoriesState>("report.repositories", {});
  const [loading, setLoading] = useStoredState<LoadingState>("report.loading", {});
  const refreshedThisVisit = useRef<Set<string>>(new Set());
  const [editorSlot, setEditorSlot] = useState<UploadSlotId | null>(null);
  const [exporting, setExporting] = useState<LoadingState>({});
  // What the PM changed in the editor: slide text, cover text, and whether the summary was hand-written.
  const [edits, setEdits] = useStoredState<Record<string, SlideEdit>>("report.edits", {});
  const [cover, setCover] = useStoredState<Partial<Record<UploadSlotId, DeckState["cover"]>>>("report.cover", {});
  // Slides the PM added by hand, per source.
  const [customSlides, setCustomSlides] = useStoredState<Partial<Record<UploadSlotId, CustomSlide[]>>>("report.customSlides", {});
  const [summaryEdited, setSummaryEdited] = useStoredState<Partial<Record<UploadSlotId, boolean>>>("report.summaryEdited", {});
  // The summary has three sources: what the generator wrote (English), its translation into the picked language,
  // and what the PM typed. The PM's text wins; otherwise the translation when one matches the language.
  const [summaryText, setSummaryText] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("report.summaryText", {});
  const [summaryTranslated, setSummaryTranslated] = useStoredState<
    Partial<Record<UploadSlotId, { language: string; source: string; bullets: string[] }>>
  >("report.summaryTranslated", {});
  const summaryEditedRef = useRef(summaryEdited);
  summaryEditedRef.current = summaryEdited;
  const [errors, setErrors] = useState<ErrorsState>({});
  const [selected, setSelected] = useStoredState<Record<string, boolean>>("report.selected", {});

  // The PM's own chosen slide order (drag-reorderable) -- frontend-only
  // until download time, when it's sent to the backend so the exported
  // .pptx matches this preview's order exactly.
  const [slideOrder, setSlideOrder] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("report.slideOrder", {});
  // Charts start collapsed -- a slide is mostly checkbox/name/chart-type
  // until the PM asks to actually see the chart.
  const [expandedCharts, setExpandedCharts] = useStoredState<Record<string, boolean>>("report.expandedCharts", {});

  // The Report's own closing-slide bullet points -- synthesized from the
  // included slides' interpretations (see final_summary_agent.py), NOT the
  // Analysis page's KPI-highlights Summary. Bullets, not one paragraph, to
  // match the reference deck's own bullet-point closing slide.
  const [summaryBullets, setSummaryBullets] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("report.summaryBullets", {});
  const [summaryLoading, setSummaryLoading] = useStoredState<LoadingState>("report.summaryLoading", {});
  const [summaryError, setSummaryError] = useState<ErrorsState>({});

  const [languages, setLanguages] = useState<LanguageOption[]>([{ code: "en", name: "English" }]);
  const [language, setLanguage] = useStoredState("report.language", "en");
  // Translated {entryId: {name, interpretation}} per slot, for whichever
  // language is picked -- mirrors what build_report puts on each slide, so
  // this on-screen list matches the .pptx before the PM ever downloads it.
  const [translations, setTranslations] = useStoredState<Partial<Record<UploadSlotId, Record<string, EntryTranslation>>>>("report.translations", {});

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  // The language list only ever needs fetching once -- it's a fixed catalog
  // of what the backend's translation_service currently supports, not
  // per-session. Falling back to English-only (the initial state above) if
  // this fails is fine -- the report always downloads, just without the
  // language picker filled in.
  useEffect(() => {
    fetchSupportedReportLanguages()
      .then((res) => setLanguages(res.languages))
      .catch(() => {});
  }, []);

  // Re-fetches translated names/interpretations whenever the picked
  // language or the set of done entries changes. English needs no fetch --
  // clearing state lets the render fall back to each entry's own English
  // text. A failed fetch (translation service down, etc.) leaves the prior
  // (or no) translations in place rather than blocking the preview.
  useEffect(() => {
    if (language === "en") {
      setTranslations((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      return;
    }
    for (const id of auditedReady) {
      const doneIds = (repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id);
      if (doneIds.length === 0) continue;
      const sessionId = auditReports[id]!.session_id;
      fetchReportTranslations(sessionId, language, doneIds)
        .then((res) => setTranslations((prev) => ({ ...prev, [id]: res.translations })))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, repositories, auditedReady]);

  useEffect(() => {
    for (const id of auditedReady) {
      if (loading[id] || refreshedThisVisit.current.has(id)) continue;
      refreshedThisVisit.current.add(id);
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      fetchAnalysisRepository(sessionId)
        .then((res) => {
          // Only accepted analyses and drill-downs: a suggested path's pending levels (and rejected
          // ones) are never offered for the report.
          const entries = res.entries.filter((e) => e.status === "approved");
          setRepositories((prev) => ({ ...prev, [id]: entries }));
          const byId = new Map(entries.map((e) => [e.id, e]));
          setSelected((prev) => {
            const next = { ...prev };
            for (const entry of entries) {
              // Stale drill-down levels are never included by default.
              if (entry.run_status === "done" && !(entry.id in next)) next[entry.id] = !isStaleEntry(entry, byId);
            }
            return next;
          });
        })
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not load this session's analyses.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  // Seeds each slot's slide order from its done entries the first time they
  // load, and appends any newly-finished entry ids at the end afterward --
  // never disturbs an order the PM already dragged into place.
  useEffect(() => {
    for (const id of auditedReady) {
      const doneIds = (repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id);
      if (doneIds.length === 0) continue;
      setSlideOrder((prev) => {
        const current = prev[id] ?? [];
        const currentSet = new Set(current);
        const missing = doneIds.filter((eid) => !currentSet.has(eid));
        if (missing.length === 0) return prev;
        return { ...prev, [id]: [...current, ...missing] };
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady]);

  const runReportSummary = (id: UploadSlotId, entryIds: string[]) => {
    const sessionId = auditReports[id]!.session_id;
    setSummaryLoading((prev) => ({ ...prev, [id]: true }));
    setSummaryError((prev) => ({ ...prev, [id]: undefined }));
    fetchReportSummary(sessionId, entryIds)
      .then((res) => {
        // A summary the PM wrote by hand while this was loading must not be overwritten.
        if (!summaryEditedRef.current[id]) setSummaryBullets((prev) => ({ ...prev, [id]: res.bullets }));
      })
      .catch((err) => {
        // Forget the signature so the next visit / selection change retries instead of
        // treating this selection as already summarized.
        summarizedFor.current[id] = undefined;
        setSummaryError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the summary agent.",
        }));
      })
      .finally(() => setSummaryLoading((prev) => ({ ...prev, [id]: false })));
  };

  // The final summary regenerates whenever the ordered, selected, done
  // entry-id list actually changes -- keyed by a signature of that exact
  // list so toggling a checkbox or reordering slides refreshes it, but
  // re-renders for unrelated reasons don't re-request it.
  const summarizedFor = useStoredRef<{ current: Partial<Record<UploadSlotId, string>> }>("report.summarizedFor", () => ({ current: {} }));
  useEffect(() => {
    for (const id of auditedReady) {
      const order = slideOrder[id] ?? [];
      const doneIds = new Set((repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id));
      const byId = new Map((repositories[id] ?? []).map((e) => [e.id, e]));
      const orderedSelectedDoneIds = buildReportTree(
        (repositories[id] ?? []).filter((e) => doneIds.has(e.id) && selected[e.id] && !isStaleEntry(e, byId)),
        order
      ).map((n) => n.entry.id);
      if (orderedSelectedDoneIds.length === 0 || summaryEdited[id]) continue;
      const signature = orderedSelectedDoneIds.join("|");
      if (summarizedFor.current[id] === signature || summaryLoading[id]) continue;
      summarizedFor.current[id] = signature;
      runReportSummary(id, orderedSelectedDoneIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady, slideOrder, selected, summaryEdited]);

  // Hand the summary back to the generator: forgetting its signature makes the effect above rebuild it.
  const regenerateSummary = (id: UploadSlotId) => {
    summarizedFor.current[id] = undefined;
    setSummaryEdited((prev) => ({ ...prev, [id]: false }));
    setSummaryText((prev) => ({ ...prev, [id]: undefined }));
  };

  // Translate the generated summary whenever the language (or the summary) changes. English needs nothing.
  useEffect(() => {
    if (language === "en") return;
    for (const id of auditedReady) {
      const source = summaryBullets[id];
      if (!source || summaryEdited[id]) continue;
      const key = source.join("|");
      const have = summaryTranslated[id];
      if (have && have.language === language && have.source === key) continue;
      translateTexts(language, source)
        .then((map) =>
          setSummaryTranslated((prev) => ({ ...prev, [id]: { language, source: key, bullets: source.map((b) => map[b] ?? b) } }))
        )
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, summaryBullets, summaryEdited]);

  // The summary exactly as it should read now: the PM's own text, else the translation, else the generated English.
  const bulletsFor = (id: UploadSlotId): string[] | null => {
    if (summaryEdited[id]) return summaryText[id] ?? [];
    const generated = summaryBullets[id];
    if (!generated) return null;
    const translated = summaryTranslated[id];
    return language !== "en" && translated?.language === language && translated.source === generated.join("|")
      ? translated.bullets
      : generated;
  };

  const toggleSelected = (entryId: string) => setSelected((prev) => ({ ...prev, [entryId]: !prev[entryId] }));

  const noFiles = AUDITED_SLOTS.every((id) => !files[id]);
  const stillChecking = Object.values(loading).some(Boolean);
  const slotsWithResults = auditedReady.filter((id) => (repositories[id] ?? []).some((e) => e.run_status === "done"));
  // The conversation talks about the first source that has results.
  const primary = slotsWithResults[0];
  const [log, setLog] = useStoredState<ReportLogEntry[]>("report.log", []);
  const say = (user: string, block: ReportLogEntry["block"]) => setLog((prev) => [...prev, { user, block }]);

  // Everything about the primary source's deck, worked out once.
  const doneEntriesRaw = primary ? (repositories[primary] ?? []).filter((e) => e.run_status === "done") : [];
  const order = (primary && slideOrder[primary]) || [];
  const byId = new Map((primary ? repositories[primary] ?? [] : []).map((e) => [e.id, e]));
  const staleIds = new Set(doneEntriesRaw.filter((e) => isStaleEntry(e, byId)).map((e) => e.id));
  const tree = buildReportTree(doneEntriesRaw, order);
  const includedTree = buildReportTree(doneEntriesRaw.filter((e) => selected[e.id] && !staleIds.has(e.id)), order);
  const slideNumbers = new Map(includedTree.map((n) => [n.entry.id, n.number]));
  const selectedEntries = includedTree.map((n) => n.entry);
  const selectedIds = selectedEntries.map((e) => e.id);

  const deck: DeckState | undefined = primary
    ? {
        selected,
        order,
        edits,
        cover: cover[primary] ?? {},
        custom: customSlides[primary] ?? [],
        bullets: bulletsFor(primary),
        bulletsEdited: !!summaryEdited[primary],
      }
    : undefined;

  const applyDeck = (next: DeckState) => {
    if (!primary) return;
    setSelected(next.selected);
    setSlideOrder((prev) => ({ ...prev, [primary]: next.order }));
    setEdits(next.edits);
    setCover((prev) => ({ ...prev, [primary]: next.cover }));
    setCustomSlides((prev) => ({ ...prev, [primary]: next.custom }));
    setSummaryEdited((prev) => ({ ...prev, [primary]: next.bulletsEdited }));
    // Only text the PM typed is stored; the generated summary stays as the generator wrote it.
    if (next.bulletsEdited) setSummaryText((prev) => ({ ...prev, [primary]: next.bullets ?? [] }));
  };

  const download = async () => {
    if (!primary) return;
    const id = primary;
    setExporting((prev) => ({ ...prev, [id]: true }));
    setErrors((prev) => ({ ...prev, [id]: undefined }));
    try {
      // Text the PM typed is translated like the rest of the slide. Text already saved in the report
      // language comes back unchanged, so this is safe to run every time.
      let slideEdits = edits;
      if (language !== "en") {
        const typed = selectedEntries
          .flatMap((e) => [edits[e.id]?.heading, edits[e.id]?.explanation, edits[e.id]?.caption])
          .filter((t): t is string => !!t?.trim());
        if (typed.length > 0) {
          const map = await translateTexts(language, [...new Set(typed)]);
          const tr = (t?: string) => (t ? (map[t] ?? t) : t);
          slideEdits = Object.fromEntries(
            Object.entries(edits).map(([k, v]) => [k, { heading: tr(v.heading), explanation: tr(v.explanation), caption: tr(v.caption) }])
          );
        }
      }
      const blob = await exportReport(auditReports[id]!.session_id, {
        slides: selectedEntries.map((e) => ({
          entry_id: e.id,
          chart_type: defaultChartType(e),
          heading: slideEdits[e.id]?.heading,
          explanation: slideEdits[e.id]?.explanation,
          caption: slideEdits[e.id]?.caption,
        })),
        language,
        custom_slides: (customSlides[id] ?? []).map((c) => ({ heading: c.heading, bullets: c.bullets })),
        cover_title: cover[id]?.title,
        cover_subtitle: cover[id]?.subtitle,
        // The summary exactly as shown (and possibly edited), so the file matches the preview.
        summary_bullets: bulletsFor(id),
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "Program Manager AI Report.pptx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not build the report." }));
    } finally {
      setExporting((prev) => ({ ...prev, [id]: false }));
    }
  };

  const replies: StageReply[] = [];
  if (noFiles) {
    replies.push({ label: "Go to Configure", main: true, onClick: () => navigate("/upload") });
  } else if (auditedReady.length === 0) {
    replies.push({ label: "Back to Audit", main: true, onClick: () => navigate("/audit") });
  } else if (!primary) {
    replies.push({ label: "Go to Analysis", main: true, onClick: () => navigate("/analysis") });
  } else {
    replies.push({
      label: "Download the report",
      main: true,
      disabled: !!exporting[primary],
      onClick: () => {
        say("Download the report", "download");
        if (selectedIds.length > 0) void download();
      },
    });
    replies.push({
      label: "Edit the slides",
      onClick: () => {
        say("I want to edit the slides", "edit");
        setEditorSlot(primary);
      },
    });
    replies.push({ label: "Change the language", onClick: () => say("Change the report language", "language") });
    replies.push({
      label: "Write the summary again",
      disabled: !!summaryLoading[primary],
      onClick: () => {
        say("Write the summary again", "summary");
        regenerateSummary(primary);
      },
    });
  }
  useStageChrome({ replies });

  const rows: ReportSlideRow[] = tree.map(({ entry, depth }) => {
    const tr = primary ? translations[primary]?.[entry.id] : undefined;
    const interpretation = edits[entry.id]?.explanation ?? tr?.interpretation ?? entry.interpretation;
    const caption = edits[entry.id]?.caption;
    return {
      entry,
      depth,
      name: edits[entry.id]?.heading || (tr?.name ?? entry.name),
      interpretation: interpretation ? shortenInterpretation(interpretation) : null,
      subtitle: caption !== undefined ? caption : entry.chain ? drilldownSubtitle(entry.chain) : "",
      number: slideNumbers.get(entry.id),
      stale: staleIds.has(entry.id),
      included: !staleIds.has(entry.id) && !!selected[entry.id],
      chartOpen: !!expandedCharts[entry.id],
    };
  });

  return (
    <>
      {noFiles && (
        <ChatMessage>
          <p>There is no audited data yet. Set up a program in Configure first, and I will build a report from your analyses.</p>
        </ChatMessage>
      )}
      {!noFiles && auditedReady.length === 0 && (
        <ChatMessage>
          <p>I can build the report once the data audit is finished. Go back and settle the open decisions, then come here.</p>
        </ChatMessage>
      )}
      {!noFiles && auditedReady.length > 0 && !primary && (
        <ChatMessage>
          {stillChecking ? (
            <ThinkingLoader variant="inline" messages={["Checking whether any analyses have finished…"]} />
          ) : (
            <p>No analyses have finished yet. Run some in Analysis first, because the report is built from the ones that finished successfully.</p>
          )}
        </ChatMessage>
      )}

      {primary && (
        <ReportChat
          analyses={doneEntriesRaw.length}
          aiSuggested={doneEntriesRaw.filter((e) => e.source === "ai_suggested").length}
          addedSlides={(customSlides[primary] ?? []).length}
          bullets={bulletsFor(primary)}
          summaryLoading={!!summaryLoading[primary]}
          summaryError={summaryError[primary]}
          onRetrySummary={() => runReportSummary(primary, selectedIds)}
          rows={rows}
          onToggle={toggleSelected}
          onToggleChart={(entryId) => setExpandedCharts((prev) => ({ ...prev, [entryId]: !prev[entryId] }))}
          languages={languages}
          language={language}
          onLanguage={setLanguage}
          log={log}
          exporting={!!exporting[primary]}
          exportError={errors[primary]}
          noSelection={selectedIds.length === 0}
        />
      )}

      {primary && editorSlot === primary && deck && (
        <ReportEditorModal
          entries={doneEntriesRaw}
          staleIds={staleIds}
          translations={translations[primary]}
          language={language}
          onTranslate={(texts) => translateTexts(language, texts)}
          deck={deck}
          coverDefaults={{ title: "Cold Chain Analysis", subtitle: files[primary]!.name.replace(/\.(xlsx|xlsm|xls|csv)$/i, "") }}
          summaryLoading={!!summaryLoading[primary]}
          summaryError={summaryError[primary]}
          onChange={applyDeck}
          onRegenerateSummary={() => regenerateSummary(primary)}
          onClose={() => setEditorSlot(null)}
        />
      )}
    </>
  );
}

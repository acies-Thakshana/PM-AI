import { useState } from "react";
import type { PivotResult } from "../api/audit";
import Modal from "./Modal";
import PivotTableCard from "./PivotTableCard";
import PivotChart from "./PivotChart";
import "./PivotModal.css";

interface PivotModalProps {
  pivot: PivotResult;
  filterSelections: Record<string, string[] | undefined>;
  onSaveFilters: (next: Record<string, string[] | undefined>) => void;
  savingFilters?: boolean;
  onClose: () => void;
}

type Tab = "table" | "chart";

export default function PivotModal({ pivot, filterSelections, onSaveFilters, savingFilters, onClose }: PivotModalProps) {
  const [tab, setTab] = useState<Tab>("table");

  return (
    <Modal title={pivot.name} onClose={onClose}>
      <div className="pivot-modal__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "table"}
          className={`pivot-modal__tab ${tab === "table" ? "pivot-modal__tab--active" : ""}`}
          onClick={() => setTab("table")}
        >
          Table
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "chart"}
          className={`pivot-modal__tab ${tab === "chart" ? "pivot-modal__tab--active" : ""}`}
          onClick={() => setTab("chart")}
        >
          Chart
        </button>
      </div>

      <div className="pivot-modal__tab-content">
        {tab === "table" ? (
          <PivotTableCard
            pivot={pivot}
            filterSelections={filterSelections}
            onSaveFilters={onSaveFilters}
            savingFilters={savingFilters}
            hideHeader
          />
        ) : (
          <PivotChart pivot={pivot} />
        )}
      </div>
    </Modal>
  );
}

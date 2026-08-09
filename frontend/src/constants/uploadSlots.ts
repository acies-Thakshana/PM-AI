import type { UploadSlotConfig, UploadSlotId } from "../types/upload";

export const UPLOAD_SLOTS: UploadSlotConfig[] = [
  {
    id: "sensiwatch",
    title: "SensiWatch Export",
    description: "Real-time shipment monitoring data exported from the SensiWatch platform.",
    required: true,
    accept: ".xlsx,.xls,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
  },
  {
    id: "coldstream",
    title: "ColdStream Export",
    description: "Trip and sensor data exported from the ColdStream monitoring platform.",
    required: false,
    accept: ".xlsx,.xls,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
  },
  {
    id: "thresholds",
    title: "Threshold & Compliance Reference",
    description: "Temperature/humidity thresholds and other compliance reference documentation.",
    required: false,
    accept: ".pdf,.doc,.docx,.xlsx,.csv,.md",
    acceptLabel: "PDF, Word, Excel, CSV, or Markdown",
  },
  {
    id: "customerKpis",
    title: "Customer KPI Profile",
    description:
      "JSON feature definitions used in the Features step (e.g. Country of Origin lookup, % In Spec formula). Nothing is computed there without this file -- see backend/data/samples/customer_kpi_profile_example.json for the format.",
    required: false,
    accept: ".json",
    acceptLabel: "JSON",
  },
];

// Only the tabular data sources get audited -- duplicate/outlier checks aren't
// meaningful for the reference documents even though their accept lists also
// permit spreadsheet formats.
export const AUDITED_SLOTS: UploadSlotId[] = ["sensiwatch", "coldstream"];

export function isAudited(id: UploadSlotId): boolean {
  return AUDITED_SLOTS.includes(id);
}

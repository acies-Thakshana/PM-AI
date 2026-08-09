export type UploadSlotId = "sensiwatch" | "coldstream" | "thresholds" | "customerKpis";

export interface UploadSlotConfig {
  id: UploadSlotId;
  title: string;
  description: string;
  required: boolean;
  accept: string;
  acceptLabel: string;
}

export type UploadStatus = "empty" | "selected" | "error";

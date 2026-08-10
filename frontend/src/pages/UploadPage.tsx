import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import SearchBar from "../components/SearchBar";
import FileUploadCard from "../components/FileUploadCard";
import StepIndicator from "../components/StepIndicator";
import { UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { FilesState } from "../App";
import "./UploadPage.css";

type ErrorsState = Partial<Record<UploadSlotId, string>>;

interface UploadPageProps {
  files: FilesState;
  onSelect: (id: UploadSlotId, file: File) => void;
  onRemove: (id: UploadSlotId) => void;
  onClearAll: () => void;
}

export default function UploadPage({ files, onSelect, onRemove, onClearAll }: UploadPageProps) {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<ErrorsState>({});

  const handleSelect = (id: UploadSlotId, file: File) => {
    onSelect(id, file);
    setErrors((prev) => ({ ...prev, [id]: undefined }));
  };

  const handleContinue = () => {
    const nextErrors: ErrorsState = {};
    for (const slot of UPLOAD_SLOTS) {
      if (slot.required && !files[slot.id]) {
        nextErrors[slot.id] = `${slot.title} is required.`;
      }
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length === 0) {
      navigate("/audit");
    }
  };

  const handleSearch = (query: string) => {
    console.log("Search:", query);
  };

  const selectedCount = Object.values(files).filter(Boolean).length;

  return (
    <div className="upload-page">
      <Header />
      <main className="upload-page__main">
        <StepIndicator current={1} />

        <div className="upload-page__search-row">
          <SearchBar onSearch={handleSearch} />
        </div>

        <div className="upload-page__intro">
          <h1 className="upload-page__heading">Upload Source Data</h1>
          <p className="upload-page__lede">
            Provide the SensiWatch export to begin. ColdStream data, threshold references, and
            customer KPI documents are optional but improve triage and reporting accuracy. SensiWatch
            and ColdStream files are reviewed by the data audit agent on the next page.
          </p>
        </div>

        <div className="upload-page__grid">
          {UPLOAD_SLOTS.map((slot) => (
            <FileUploadCard
              key={slot.id}
              config={slot}
              file={files[slot.id]}
              error={errors[slot.id]}
              onSelect={(file) => handleSelect(slot.id, file)}
              onRemove={() => onRemove(slot.id)}
            />
          ))}
        </div>

        <div className="upload-page__actions">
          <span className="upload-page__count">{selectedCount} of {UPLOAD_SLOTS.length} files selected</span>
          <div className="upload-page__buttons">
            <button type="button" className="upload-page__btn upload-page__btn--secondary" onClick={onClearAll}>
              Clear All
            </button>
            <button type="button" className="upload-page__btn upload-page__btn--primary" onClick={handleContinue}>
              Upload &amp; Continue
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

import GenerateReportPanel from "../../components/GenerateReportPanel";

export default function ReportStudio() {
  return (
    <div>
      <GenerateReportPanel />
      <div className="panel">
        <h2>
          About This Report
          <span className="hint">what the generator uses as its source data</span>
        </h2>
        <p className="flag-explanation">
          The PPTX generator runs a 2-agent pipeline (Insight Analyst + Report Composer) directly over the
          SensiWatch/ColdStream trip data loaded on the Data Upload page - KPIs, flagged trips, and product/bloom
          risk tables are the same live numbers shown across this dashboard. The narrative and recommendations are
          grounded in a chocolate cold chain domain knowledge base (fat bloom vs. sugar bloom mechanisms, trip
          triage root causes). Load data first if you haven't - report generation will fail without it.
        </p>
      </div>
    </div>
  );
}

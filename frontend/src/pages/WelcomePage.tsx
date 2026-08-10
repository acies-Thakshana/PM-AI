import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import { IconUpload, IconShieldSearch, IconSparkle, IconGrid, IconClipboard, IconChevronRight } from "../components/icons";
import "./WelcomePage.css";

const STEPS = [
  {
    step: 1,
    title: "Upload",
    icon: <IconUpload />,
    color: "blue",
    description: "Provide your SensiWatch/ColdStream exports, threshold references, and any KPI or analysis definition profiles.",
  },
  {
    step: 2,
    title: "Audit",
    icon: <IconShieldSearch />,
    color: "teal",
    description: "A deterministic data-quality audit, together with the AI agent, flags empty columns, duplicates, and outliers before anything downstream trusts the numbers.",
  },
  {
    step: 3,
    title: "Features",
    icon: <IconSparkle />,
    color: "purple",
    description: "Compute KPIs from your Customer KPI Profile, or build new ones together with the AI agent from your data's own columns.",
  },
  {
    step: 4,
    title: "Analysis",
    icon: <IconGrid />,
    color: "amber",
    description: "Build breakdowns with interactive slicers, view them as a table or a chart, or work with the AI agent to surface breakdowns worth looking at.",
  },
  {
    step: 5,
    title: "Report",
    icon: <IconClipboard />,
    color: "blue",
    description: "Download a PowerPoint report with native, editable charts built fresh from whatever pivots and filters you currently have set.",
  },
] as const;

export default function WelcomePage() {
  const navigate = useNavigate();

  return (
    <div className="welcome-page">
      <Header subtitle="Welcome" />
      <main className="welcome-page__main">
        <section className="welcome-page__hero">
          <h1 className="welcome-page__title">Program Manager AI</h1>
          <p className="welcome-page__lede">
            A Cold-Chain/Post-Harvest program management tool. Upload your raw shipment data and this
            application takes you from messy spreadsheets to a clean, audited dataset, engineered KPIs,
            interactive analysis, and a downloadable report.
          </p>
          <button type="button" className="welcome-page__cta" onClick={() => navigate("/upload")}>
            Get Started <IconChevronRight />
          </button>
        </section>

        <section className="welcome-page__flow">
          <h2 className="welcome-page__flow-title">How it works</h2>
          <div className="welcome-page__steps">
            {STEPS.map((s, idx) => (
              <div className="welcome-page__step" key={s.step}>
                <div className="welcome-page__step-top">
                  <span className={`welcome-page__step-icon welcome-page__step-icon--${s.color}`}>{s.icon}</span>
                  <span className="welcome-page__step-number">Step {s.step}</span>
                </div>
                <h3 className="welcome-page__step-title">{s.title}</h3>
                <p className="welcome-page__step-description">{s.description}</p>
                {idx < STEPS.length - 1 && <span className="welcome-page__step-connector" aria-hidden="true" />}
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

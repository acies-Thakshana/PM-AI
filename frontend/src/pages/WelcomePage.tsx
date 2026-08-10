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
    description: "Provide your SensiWatch/ColdStream exports, threshold references, and any KPI or pivot definition profiles.",
  },
  {
    step: 2,
    title: "Audit",
    icon: <IconShieldSearch />,
    color: "teal",
    description: "A deterministic data-quality audit flags empty columns, duplicates, and outliers before anything downstream trusts the numbers.",
  },
  {
    step: 3,
    title: "Features",
    icon: <IconSparkle />,
    color: "purple",
    description: "Compute KPIs from your Customer KPI Profile, or ask the AI agent to suggest new ones from your data's own columns.",
  },
  {
    step: 4,
    title: "Analysis",
    icon: <IconGrid />,
    color: "amber",
    description: "Build pivot tables with interactive slicers, view them as a table or a chart, or ask AI to suggest breakdowns worth looking at.",
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
            A cold-chain program management tool. Upload your raw shipment exports and this app takes you
            from messy spreadsheets to a clean, audited dataset, engineered KPIs, interactive pivot analysis,
            and a downloadable report -- with a data-quality audit and AI assistance along the way, never
            deciding the numbers for you.
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

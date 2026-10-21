import { useContext } from "react";
import { InShellContext } from "../context/inShell";
import "./Header.css";

interface HeaderProps {
  subtitle?: string;
}

export default function Header({ subtitle = "Data Upload" }: HeaderProps) {
  // The app shell has its own logo and stage list.
  if (useContext(InShellContext)) return null;
  return (
    <header className="app-header">
      <div className="app-header__inner">
        <div className="app-header__brand">
          <img src="/carrier-logo.svg" alt="Carrier Global" className="app-header__logo" />
          <div className="app-header__divider" />
          <div className="app-header__title">
            <span className="app-header__product">Program Manager AI</span>
            <span className="app-header__subtitle">{subtitle}</span>
          </div>
        </div>
      </div>
    </header>
  );
}

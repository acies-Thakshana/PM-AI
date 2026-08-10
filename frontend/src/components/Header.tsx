import "./Header.css";

export default function Header() {
  return (
    <header className="app-header">
      <div className="app-header__inner">
        <div className="app-header__brand">
          <img src="/carrier-logo.svg" alt="Carrier Global" className="app-header__logo" />
          <div className="app-header__divider" />
          <div className="app-header__title">
            <span className="app-header__product">Program Manager AI</span>
            <span className="app-header__subtitle">Data Upload</span>
          </div>
        </div>
      </div>
    </header>
  );
}

import type { ReactNode } from "react";
import "./PageHeader.css";

interface PageHeaderProps {
  icon: ReactNode;
  title: string;
  subtitle: string;
  action?: ReactNode;
}

export default function PageHeader({ icon, title, subtitle, action }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div className="page-header__left">
        <span className="page-header__badge">{icon}</span>
        <div>
          <h1 className="page-header__title">{title}</h1>
          <p className="page-header__subtitle">{subtitle}</p>
        </div>
      </div>
      {action && <div className="page-header__action">{action}</div>}
    </div>
  );
}

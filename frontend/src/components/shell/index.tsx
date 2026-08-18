import type { HTMLAttributes, ReactNode } from "react";

type AppShellProps = HTMLAttributes<HTMLDivElement>;

export function AppShell({ className = "", ...props }: AppShellProps) {
  return <div className={`df-app workstation ${className}`.trim()} {...props} />;
}

type TopBarProps = HTMLAttributes<HTMLElement>;

export function TopBar({ className = "", ...props }: TopBarProps) {
  return <header className={`df-topbar workstation-topbar ${className}`.trim()} {...props} />;
}

type SidebarProps = HTMLAttributes<HTMLElement> & {
  open: boolean;
};

export function Sidebar({ open, className = "", ...props }: SidebarProps) {
  return (
    <aside
      className={`df-sidebar nav${open ? " open" : ""} ${className}`.trim()}
      aria-hidden={!open}
      {...props}
    />
  );
}

type AppShellBodyProps = HTMLAttributes<HTMLDivElement> & {
  navigationOpen: boolean;
  inspector?: ReactNode;
};

export function AppShellBody({
  navigationOpen,
  inspector,
  className = "",
  children,
  ...props
}: AppShellBodyProps) {
  const stateClasses = `${navigationOpen ? " nav-open" : ""}${inspector ? " has-inspector" : ""}`;
  return (
    <div className={`df-app-body workstation-body${stateClasses} ${className}`.trim()} {...props}>
      {children}
      {inspector}
    </div>
  );
}

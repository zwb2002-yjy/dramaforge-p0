import type { ReactNode } from "react";
import { Drawer } from "../ui";

/** Desktop navigation remains inline; the library owns the narrow-window overlay. */
export function ContextNavigation({
  modal,
  open,
  onClose,
  children,
}: {
  modal: boolean;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!modal) return <>{children}</>;
  return (
    <Drawer
      inline
      open={open}
      onClose={onClose}
      title="二级导航"
      placement="left"
      closeLabel="关闭二级导航"
      className="df-navigation-drawer"
    >
      {children}
    </Drawer>
  );
}

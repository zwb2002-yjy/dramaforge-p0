import { Button } from "antd";
import { createLink } from "@tanstack/react-router";
import { forwardRef, type AnchorHTMLAttributes } from "react";

type ActionLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "type" | "color"> & {
  tone?: "default" | "primary" | "ghost";
};

const RoutedButton = forwardRef<HTMLAnchorElement, ActionLinkProps>(function RoutedButton(
  { tone = "default", ...props },
  ref,
) {
  return (
    <Button
      {...props}
      ref={ref}
      autoInsertSpace={false}
      type={tone === "primary" ? "primary" : tone === "ghost" ? "text" : "default"}
    />
  );
});

/** Ant Design action appearance with TanStack's client navigation and dirty-state guards. */
export const ActionLink = createLink(RoutedButton);

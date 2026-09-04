import {
  forwardRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";

function classes(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

type ButtonTone = "default" | "primary" | "accent" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: ButtonTone;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, tone = "default", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={classes("df-btn", tone !== "default" && tone, className)}
      {...props}
    />
  );
});

type CardProps = HTMLAttributes<HTMLElement> & {
  selected?: boolean;
};

export function Card({ className, selected = false, ...props }: CardProps) {
  return <article className={classes("df-card", selected && "selected", className)} {...props} />;
}

type PageHeaderProps = HTMLAttributes<HTMLElement> & {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
};

export function PageHeader({ title, eyebrow, actions, className, ...props }: PageHeaderProps) {
  return (
    <header className={classes("df-page-header", className)} {...props}>
      <div>
        {eyebrow && <p className="kicker">{eyebrow}</p>}
        <h1>{title}</h1>
      </div>
      {actions && <div className="df-page-header-actions">{actions}</div>}
    </header>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={classes("df-input", className)} {...props} />;
  },
);

type TabsProps = HTMLAttributes<HTMLDivElement> & {
  label: string;
};

export function Tabs({ label, className, ...props }: TabsProps) {
  return (
    <div role="tablist" aria-label={label} className={classes("df-tabs", className)} {...props} />
  );
}

type TabProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean;
};

export function Tab({ active = false, className, ...props }: TabProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      className={classes("df-tab", active && "active", className)}
      {...props}
    />
  );
}

type BadgeTone = "default" | "success" | "warning" | "danger" | "info" | "selected";

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: BadgeTone;
};

const badgeToneClass: Record<BadgeTone, string> = {
  default: "",
  success: "ok",
  warning: "warn",
  danger: "err",
  info: "info",
  selected: "verdigris",
};

export function Badge({ tone = "default", className, ...props }: BadgeProps) {
  return <span className={classes("df-badge", badgeToneClass[tone], className)} {...props} />;
}

import {
  forwardRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
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
  description?: ReactNode;
  actions?: ReactNode;
};

export function PageHeader({
  title,
  eyebrow,
  description,
  actions,
  children,
  className,
  ...props
}: PageHeaderProps) {
  return (
    <header className={classes("df-page-header", className)} {...props}>
      <div className="df-page-header-copy">
        {eyebrow && <p className="kicker">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="df-page-description">{description}</p>}
        {children}
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

/** Native controls retain browser semantics, validation, refs and event types. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...props }, ref) {
    return <select ref={ref} className={classes("df-input", className)} {...props} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={classes("df-input", className)} {...props} />;
});

export const Checkbox = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { type?: "checkbox" }
>(function Checkbox({ className, type = "checkbox", ...props }, ref) {
  return <input ref={ref} type={type} className={classes("df-checkbox", className)} {...props} />;
});

/** Wrap exactly one labelled control; keep checkbox/radio groups in a fieldset. */
export function Field({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={classes("df-field", className)} {...props} />;
}

type TabsProps = HTMLAttributes<HTMLDivElement> & {
  label: string;
};

export function Tabs({ label, className, onKeyDown, ...props }: TabsProps) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={classes("df-tabs", className)}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
        const tabs = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>(
            ':scope > button[role="tab"]:not(:disabled)',
          ),
        );
        const index = tabs.indexOf(event.target as HTMLButtonElement);
        if (index < 0 || tabs.length === 0) return;
        let next: number;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault();
        tabs[next].focus();
        tabs[next].click();
      }}
      {...props}
    />
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
      tabIndex={active ? 0 : -1}
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

export { Disclosure } from "./Disclosure";

/** Shared, calm empty state. Actions stay explicit and owned by the feature. */
export function EmptyState({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="df-empty-state">
      {icon && (
        <span className="df-empty-state-icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {children}
    </section>
  );
}

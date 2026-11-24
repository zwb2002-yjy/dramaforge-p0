import { Children, type HTMLAttributes, type ReactNode } from "react";
import { Descriptions, List, Typography } from "antd";

/** Shared section heading; feature code supplies actions and product vocabulary. */
export function SectionHeader({
  title,
  actions,
  children,
}: {
  title: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="df-card-header df-section-header">
      <div className="df-section-title">
        <Typography.Title level={2}>{title}</Typography.Title>
        {children}
      </div>
      {actions && <div className="df-section-actions">{actions}</div>}
    </header>
  );
}

/** Label/value facts share the existing summary recipe, including long identities. */
export function MetadataList({
  items,
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  items: { label: string; value: ReactNode; testId?: string }[];
}) {
  return (
    <Descriptions
      {...props}
      className={className}
      size="small"
      column={1}
      items={items.map(({ label, value, testId }) => ({
        key: label,
        label,
        children: <span data-testid={testId}>{value}</span>,
      }))}
    />
  );
}

export function RecordList({
  className = "",
  children,
  ...props
}: HTMLAttributes<HTMLUListElement>) {
  return (
    <List
      role="list"
      {...props}
      className={`df-record-list ${className}`}
      split={false}
      dataSource={Children.toArray(children)}
      renderItem={(item) => item}
    />
  );
}

/** A record keeps its title, state, secondary facts and action in stable columns. */
export function RecordItem({
  title,
  meta,
  status,
  actions,
  selected = false,
  children,
  className = "",
  ...props
}: Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  title: ReactNode;
  meta?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  selected?: boolean;
}) {
  return (
    <List.Item className={`df-record-item ${className}`} data-selected={selected} {...props}>
      <div className="df-record-content">
        <div className="df-record-title">
          <strong>{title}</strong>
          {status}
        </div>
        {meta && <div className="df-record-meta">{meta}</div>}
        {children}
      </div>
      {actions && <div className="df-record-actions">{actions}</div>}
    </List.Item>
  );
}

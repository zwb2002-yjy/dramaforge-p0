import type { ReactNode } from "react";
import type { ResearchRevisionRead } from "./api";

const labels: Record<string, string> = {
  text: "正文",
  description: "描述",
  display_name: "名称",
  aliases: "别名",
  coverage_note: "覆盖范围",
  theme: "主题",
  interpretation: "释义",
  related_material: "关联资料",
  items: "时间线",
  time: "时间",
  label: "名称",
  precision: "精度",
  start: "开始",
  end: "结束",
  related_person_ids: "相关人物",
  related_place_ids: "相关地点",
  related_entry_ids: "相关知识",
  participant_entry_ids: "参与人物",
  place_entry_ids: "相关地点",
  event_entry_id: "关联事件",
  public_url: "公开地址",
  locator_note: "出处",
};

export function ContentFields({ value }: { value: Record<string, unknown> }) {
  function display(item: unknown): ReactNode {
    if (Array.isArray(item)) {
      return (
        <ul>
          {item.map((child, index) => (
            <li key={index}>{display(child)}</li>
          ))}
        </ul>
      );
    }
    if (item && typeof item === "object")
      return <ContentFields value={item as Record<string, unknown>} />;
    return String(item ?? "");
  }
  const fields = Object.entries(value).filter(
    ([key, item]) =>
      key !== "schema_version" &&
      item != null &&
      item !== "" &&
      !(Array.isArray(item) && !item.length),
  );
  return (
    <dl>
      {fields.map(([key, item]) => (
        <div key={key}>
          <dt>{labels[key] ?? key}</dt>
          <dd>{display(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

const checks: Record<string, string> = {
  unverified: "待核实",
  user_asserted: "用户确认",
  corroborated: "已交叉印证",
};

export function RevisionDetails({ revision }: { revision: ResearchRevisionRead }) {
  return (
    <>
      <p>{checks[revision.verification] ?? revision.verification}</p>
      <ContentFields value={revision.body} />
      {revision.citations.length ? (
        <ul aria-label="引用来源">
          {revision.citations.map((citation) => (
            <li key={citation.id}>
              <q>{citation.quoted_text || "引用整段"}</q>
              <span>
                {" "}
                · {citation.extraction_method}
                {citation.source_available ? "" : " · 来源已不可用"}
              </span>
              {citation.locator_override && <ContentFields value={citation.locator_override} />}
              {citation.limitations?.length ? <p>{citation.limitations.join("、")}</p> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p>此版本未附引文。</p>
      )}
    </>
  );
}

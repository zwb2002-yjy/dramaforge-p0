import type { components } from "../shared/api/generated";

const purposes:Record<string,string>={research_text:"研究解读",image_generation:"图像生成",video_generation:"视频生成",voice_generation:"语音生成",reference_delivery:"交付参考素材",director_text:"导演对话"};
const modes:Record<string,string>={current:"当前策略",allowlisted:"仅允许清单内目的地",local_only:"仅本地"};
export function EgressSummary({egress}:{egress:components["schemas"]["EgressPreview"]}) {
  const {payload_summary:p, source_eligibility:source}=egress;
  const parts=[p.text_count&&`文本 ${p.text_count} 项`,p.reference_count&&`参考素材 ${p.reference_count} 项`,p.file_count&&`来源资料 ${p.file_count} 份`,p.fragment_count&&`原文片段 ${p.fragment_count} 段`].filter(Boolean);
  return <section aria-label="本次发送范围">
    <strong>本次发送范围</strong>
    <p>{parts.join("、")||"无外发材料"} · {egress.required_purposes.map(v=>purposes[v]??v).join("、")}</p>
    <p>目的地：{egress.destination_host??(egress.actual_processing_location==="local"?"本地处理":"未声明上游地址")} · {{unknown:"处理位置待核实",local:"本地",external:"外部处理"}[egress.actual_processing_location]}</p>
    <p>{modes[egress.mode]??egress.mode} · 策略版本 {egress.policy_revision}
      {source.status!=="no_source_inputs" && <> · {source.status==="legacy_undeclared"?"旧素材未登记来源":source.allowed?"来源用途符合":"来源用途受限"}</>}
    </p>
    {!!egress.blockers.length&&<p role="alert">本次发送受阻：{egress.blockers.join("、")}</p>}
  </section>;
}

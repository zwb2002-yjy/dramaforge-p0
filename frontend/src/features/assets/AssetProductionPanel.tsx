import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Dialog, Field, Input, Select, Textarea } from "../../components/ui";
import { EgressSummary } from "../../components/EgressSummary";
import { artifactContentUrl } from "../../lib/api";
import { nodeRunStatusLabel } from "../../lib/runLabels";
import { queryKeys } from "../../lib/queryKeys";
import { assetDecisionKey, createAssetDraft, listAssetProduction, previewAssetProduction, submitAssetProduction,
  type AssetRead,type AssetPlanInput,type AssetPlan } from "./api";

export function NewAssetSetting({projectId,onClose,onCreated}:{projectId:string;onClose:()=>void;onCreated:()=>void}){
  const [name,setName]=useState(""),[kind,setKind]=useState("character"),[key,setKey]=useState(assetDecisionKey);
  const create=useMutation({mutationFn:()=>createAssetDraft(projectId,key,name.trim(),kind),retry:false,onSuccess:onCreated});
  return <Dialog title="新建素材设定" open onClose={()=>{if(!create.isPending)onClose()}} actions={<><Button disabled={create.isPending} onClick={onClose}>取消</Button>
    <Button disabled={!name.trim()||create.isPending} onClick={()=>create.mutate()}>保存设定草稿</Button></>}>
    <Field><span>素材名称</span><Input value={name} maxLength={160} disabled={create.isPending} onChange={e=>{setName(e.target.value);setKey(assetDecisionKey())}}/></Field>
    <Field><span>素材类别</span><Select value={kind} disabled={create.isPending} onChange={v=>{setKind(v);setKey(assetDecisionKey())}} options={[{value:"character",label:"人物"},{value:"scene",label:"场景"},{value:"image",label:"图片"},{value:"video",label:"视频"},{value:"audio",label:"声音"}]}/></Field>
    {create.isError&&<p role="alert">{create.error.message}</p>}
  </Dialog>;
}

export function AssetProductionPanel({projectId,asset}:{projectId:string;asset:AssetRead}){
 const client=useQueryClient();
 const [text,setText]=useState("");
 const [preview,setPreview]=useState<{input:AssetPlanInput;plan:AssetPlan}|null>(null);
 const voice=asset.kind==="audio",video=asset.kind==="video",media=voice?"语音":video?"视频":"图片";
 const key=["asset-production",projectId,asset.id];
 const history=useQuery({queryKey:key,queryFn:({signal})=>listAssetProduction(projectId,asset.id,signal),retry:false,
   refetchInterval:q=>q.state.data?.some(row=>["queued","running","leased","submitted"].includes(row.status))?2500:false});
 const input:AssetPlanInput=voice ? {stage:"asset_voice",request:{expected_asset_version:asset.version,text:text.trim()}}
   :video?{stage:"asset_video",request:{expected_asset_version:asset.version,requirements:{summary:text.trim()},mode_id:"text_to_video"}}
   :{stage:"asset_image",request:{expected_asset_version:asset.version,requirements:{summary:text.trim()},mode_id:"text_to_image",operation:"image_generate"}};
 const show=preview && JSON.stringify(input)===JSON.stringify(preview.input) ? preview :null;
 const planQuery=useMutation({mutationFn:async(decision:AssetPlanInput)=>({input:decision,plan:await previewAssetProduction(projectId,asset.id,decision)}),
   retry:false,onSuccess:value=>setPreview(value)});
 const send=useMutation({mutationFn:()=>{
   if(!show||show.plan.egress.blockers.length)throw Error("请先重新预览并核对许可");
   return submitAssetProduction(projectId,asset.id,show.input,show.plan);
 },retry:false,onSettled:()=>{void client.invalidateQueries({queryKey:key})},onSuccess:()=>setPreview(null)});
 return <section aria-label={media+"制作"}>
   <Field><span>{voice?"配音文字":media+"制作要求"}</span><Textarea rows={3} value={text} disabled={send.isPending}
     maxLength={voice?64000:16000} onChange={e=>{setText(e.target.value);setPreview(null);send.reset()}}/></Field>
   <Button disabled={!text.trim()||planQuery.isPending||send.isPending} onClick={()=>planQuery.mutate(input)}>预览{media}制作</Button>
   {planQuery.error&&<p role="alert">{planQuery.error.message}</p>}
   {show && <section aria-label="素材制作预览">
     <p>{show.plan.model_id} · 最多 {show.plan.max_provider_operations} 次模型请求</p>
     <p>{'prompt' in show.plan ? show.plan.prompt : show.plan.text}</p>
     {"segments" in show.plan && show.plan.requires_concat && <p>分为 {show.plan.segments.length} 段，完成后在本地拼接。</p>}
     {"voice_options" in show.plan && <p>音色：{String(show.plan.voice_options.voice_id??"")}</p>}
     <EgressSummary egress={show.plan.egress}/>
     <Button disabled={!!show.plan.egress.blockers.length||send.isPending} onClick={()=>send.mutate()}>确认按此预览生成{media}</Button>
   </section>}
   {send.error && <p role="alert">{send.error.message}。可刷新制作记录核对原任务。</p>}
   {send.data && <p role="status">制作请求已受理。</p>}
   <h4>制作记录</h4>
   <Button disabled={history.isFetching} onClick={()=>void history.refetch()}>刷新制作记录</Button>
   {history.isError&&<p role="alert">{history.error.message}</p>}
   {history.data?.length===0&&<p>尚无制作记录。</p>}
   <ul>{history.data?.map(row=><li key={row.node_run_id}>
     <span>第 {row.attempt_no} 次 · {nodeRunStatusLabel(row.status)}</span>
     {row.result_artifact_id && <a href={artifactContentUrl(projectId,row.result_artifact_id)} target="_blank" rel="noreferrer">打开生成结果</a>}
   </li>)}</ul>
 </section>;
}

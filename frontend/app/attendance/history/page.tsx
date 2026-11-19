"use client";

import {useEffect,useState} from "react";
import InstructorGate from "../InstructorGate";
import InstructorSidebar from "../InstructorSidebar";
import {api,apiBase,SessionHistoryItem,SessionView} from "../lib/api";

function SessionHistory(){
 const [items,setItems]=useState<SessionHistoryItem[]>([]);
 const [selected,setSelected]=useState<SessionView|null>(null);
 const [loading,setLoading]=useState(true);
 const [loadingId,setLoadingId]=useState("");
 const [error,setError]=useState("");
 const [exporting,setExporting]=useState(false);

 useEffect(()=>{let active=true;api<SessionHistoryItem[]>("/api/sessions/history").then(rows=>{if(active)setItems(rows)}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[]);

 async function openSession(item:SessionHistoryItem){
  setLoadingId(item.id);setError("");
  try{const detail=await api<SessionView>("/api/sessions/"+item.id);setSelected(detail)}
  catch(e:any){setError(e.message||"Could not load this session.")}
  finally{setLoadingId("")}
 }

 async function downloadExport(){
  if(!selected)return;
  setExporting(true);setError("");
  try{
   const response=await fetch(apiBase()+"/api/sessions/"+selected.id+"/export.zip",{credentials:"include",cache:"no-store"});
   if(!response.ok)throw new Error("Export failed. Sign in again and retry.");
   const blob=await response.blob();const url=URL.createObjectURL(blob);
   const anchor=document.createElement("a");anchor.href=url;anchor.download="nexus-attendance-"+selected.id+".zip";
   document.body.appendChild(anchor);anchor.click();anchor.remove();URL.revokeObjectURL(url);
  }catch(e:any){setError(e.message||"Could not download the export.")}
  finally{setExporting(false)}
 }

 return <div className="shell"><InstructorSidebar active="history"/>
  <main className="content"><header className="top"><div><div className="eyebrow">NEXUS · RECORDS</div><h1>Attendance history</h1><div className="muted">Open a past session to review its roster and status changes.</div></div></header>
   {error&&<div className="error">{error}</div>}
   <div className="history-columns">
    <section className="panel"><div className="panelhead"><div><h2>Past sessions</h2><div className="muted">Most recent first · up to 200 sessions</div></div><span className="tag ready">{items.length} SESSIONS</span></div>
     {loading?<div className="loading">Loading sessions…</div>:items.length?items.map(item=><button className={"history-item"+(selected?.id===item.id?" selected":"")} key={item.id} onClick={()=>openSession(item)} disabled={loadingId===item.id}><span><b>{item.class_name}</b><small>{new Date(item.started_at).toLocaleString()}</small></span><span className={"tag "+(item.status==="active"?"live":"off")}>{loadingId===item.id?"OPENING…":item.status.toUpperCase()}</span></button>):<div className="note">No attendance sessions have been recorded yet.</div>}
    </section>
    <section>
     {!selected?<div className="panel"><div className="loading">Choose a session to view its attendance roster and audit trail.</div></div>:<>
      <div className="panel"><div className="panelhead"><div><div className="eyebrow">{selected.class_name}</div><h2>Session details</h2><div className="muted">{new Date(selected.started_at).toLocaleString()} · {selected.students.length} students</div></div><span className={"tag "+(selected.status==="active"?"live":"off")}>{selected.status.toUpperCase()}</span></div><div className="controls"><button className="btn" onClick={downloadExport} disabled={exporting}>{exporting?"Preparing export…":"Download roster + audit CSVs"}</button></div><div className="footerhint">Downloads one ZIP containing attendance-roster.csv and attendance-audit-trail.csv.</div></div>
      <div className="panel"><div className="panelhead"><div><h2>Roster</h2><div className="muted">Attendance status for this session</div></div></div><div className="history-table-wrap"><table className="history-table"><thead><tr><th>Student</th><th>Code</th><th>Status</th><th>Marked</th></tr></thead><tbody>{selected.students.map(student=><tr key={student.id}><td>{student.first_name} {student.surname}</td><td>{student.student_code}</td><td><span className={"state "+student.attendance}>{student.attendance?.toUpperCase()}</span></td><td>{student.marked_at?new Date(student.marked_at).toLocaleTimeString():"—"}</td></tr>)}</tbody></table></div></div>
      <div className="panel"><div className="panelhead"><div><h2>Audit trail</h2><div className="muted">Every recorded status transition, newest first</div></div><span className="tag off">{selected.audit_log.length} EVENTS</span></div>{selected.audit_log.length?<div className="review-history">{selected.audit_log.map(event=><div className="review-entry" key={event.id}><div><b>{event.first_name} {event.surname}</b><span className="muted"> · {event.previous_status} → {event.new_status}</span><div className="pmeta">{event.actor} · {event.reason}</div></div><time className="pmeta">{new Date(event.created_at).toLocaleString()}</time></div>)}</div>:<div className="note">No status changes were recorded.</div>}</div>
     </>}
    </section>
   </div>
  </main>
 </div>
}

export default function HistoryPage(){return <InstructorGate><SessionHistory/></InstructorGate>}

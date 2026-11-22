"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {api,json,SessionView,Student} from "../lib/api";
import {Camera,Clock3,MonitorPlay,RefreshCw} from "lucide-react";
import InstructorGate from "../InstructorGate";
import InstructorSidebar from "../InstructorSidebar";

function RemoteAttendanceControl(){
 const [groups,setGroups]=useState<string[]>([]),[readyGroups,setReadyGroups]=useState<string[]>([]),[className,setClassName]=useState(""),[activeSession,setActiveSession]=useState<SessionView|null>(null),[loading,setLoading]=useState(true),[starting,setStarting]=useState(false),[ending,setEnding]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
 async function load(){setError("");try{const [names,roster,latest]=await Promise.all([api<string[]>("/api/classes"),api<Student[]>("/api/students"),api<SessionView|null>("/api/sessions/latest")]);const ready=Array.from(new Set(roster.filter(student=>student.enrolled).map(student=>student.class_name))).sort((a,b)=>a.localeCompare(b));setGroups(names);setReadyGroups(ready);if(latest?.status==="active"){setActiveSession(latest);setClassName(latest.class_name)}else{setActiveSession(null);setClassName(current=>names.includes(current)?current:ready[0]||names[0]||"")}}catch(e:any){setError(e.message||"Could not connect to the NEXUS backend.")}finally{setLoading(false)}}
 useEffect(()=>{void load()},[]);
 useEffect(()=>{if(!activeSession?.id)return;let live=true;const refresh=async()=>{try{const updated=await api<SessionView>(`/api/sessions/${activeSession.id}`);if(live){setActiveSession(updated);if(updated.status!=="active")setNotice("Attendance window finished. The classroom camera should be off.")}}catch{}};const timer=window.setInterval(()=>void refresh(),2000);return()=>{live=false;window.clearInterval(timer)}},[activeSession?.id]);
 async function start(){if(!className)return;setStarting(true);setError("");setNotice("");try{const created=await api<{id:string;class_name:string;status:string}>("/api/sessions",json({class_name:className,late_after_seconds:30,absent_after_seconds:60}));const view=await api<SessionView>(`/api/sessions/${created.id}`);setActiveSession(view);setNotice("Attendance started. The NEXUS attendance console on the classroom computer will wake its camera when it detects this session.")}catch(e:any){setError(e.message||"Could not start attendance.")}finally{setStarting(false)}}
 async function end(){if(!activeSession)return;setEnding(true);setError("");try{const updated=await api<SessionView>(`/api/sessions/${activeSession.id}/close`,{method:"POST"});setActiveSession(updated);setNotice("Attendance session ended. The classroom camera will stop after its console refreshes.")}catch(e:any){setError(e.message||"Could not end this session.")}finally{setEnding(false)}}
 const active=activeSession?.status==="active";
 return <div className="shell"><InstructorSidebar active="remote"/><main className="content remote-content"><header className="top"><div><div className="eyebrow">NEXUS · PHONE CONTROL</div><h1>Remote attendance</h1></div><Link className="btn secondary" href="/attendance">Instructor dashboard</Link></header>
  <section className="remote-card"><div className="remote-icon"><MonitorPlay size={27}/></div><div className="eyebrow">CLASSROOM COMPUTER CAMERA</div><h2>{active?"Attendance is running":"Start attendance from your phone"}</h2><p className="muted">This page sends a start command to NEXUS. The camera stays on the classroom computer; this phone does not stream video.</p>
   {active?<div className="remote-active"><span className="remote-pulse"/><div><b>{activeSession?.class_name}</b><small>Attendance session active · camera command sent to the computer console</small></div><span className="tag live">ACTIVE</span></div>:<div className="remote-picker"><label className="field"><span>CLASS / GROUP</span><select value={className} onChange={event=>setClassName(event.target.value)} disabled={loading||starting}><option value="">{loading?"Loading groups…":"Choose a group"}</option>{groups.map(group=><option key={group} value={group}>{group}</option>)}</select></label><div className="remote-timing"><Clock3 size={15}/><span>Demo window: 30 sec on time · 30 sec late · absent after 60 sec</span></div></div>}
   {error&&<div className="error">{error}</div>}{notice&&<div className={active?"success":"note"}>{notice}</div>}
   {active?<button className="btn red remote-main-button" onClick={()=>void end()} disabled={ending}>{ending?"Ending session…":"End attendance session"}</button>:<button className="btn remote-main-button" onClick={()=>void start()} disabled={loading||starting||!className||!readyGroups.includes(className)}><Camera size={17}/>{starting?"Starting attendance…":"Start attendance on classroom computer"}</button>}
   {!active&&className&&!readyGroups.includes(className)&&<div className="warning">This group needs at least one student with all seven captured face views before attendance can start.</div>}
   <div className="remote-requirements"><RefreshCw size={14}/><span>Keep the instructor dashboard open and signed in on the classroom computer. It checks for remote starts and activates its camera for the attendance window.</span></div>
  </section><p className="muted remote-footer">Phone and classroom computer must be on the same Wi-Fi. Sign in with instructor access on this page first.</p>
 </main></div>;
}

export default function RemoteAttendancePage(){return <InstructorGate><RemoteAttendanceControl/></InstructorGate>}

"use client";
import {useState} from "react";
import Link from "next/link";
import {ArrowLeft,Mail} from "lucide-react";
import {api,json} from "../../lib/api";

export default function ForgotPassword(){
 const [email,setEmail]=useState(""),[sent,setSent]=useState(false),[error,setError]=useState(""),[working,setWorking]=useState(false);
 async function requestReset(){setError("");setWorking(true);try{await api("/api/phone/password-reset/request",json({email}));setSent(true)}catch(e:any){setError(e.message)}finally{setWorking(false)}}
 return <div className="centerpage"><main className="mobilebox"><Link href="/attendance/student" className="muted inline"><ArrowLeft size={14}/> Back to sign in</Link><div className="eyebrow" style={{marginTop:21}}>ACCOUNT RECOVERY</div><div className="inline" style={{justifyContent:"space-between"}}><h1>Forgot your password?</h1><Mail color="#087f89"/></div>
 {sent?<div className="success" style={{marginTop:18}}>If an account matches that email, a reset link will arrive shortly. The link expires in 30 minutes. If it doesn’t arrive, contact your instructor.</div>:<><p className="muted">Enter the email address registered with your student account. We’ll send a one-time reset link if an account matches.</p><div className="field"><label>STUDENT EMAIL</label><input type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="student@example.com"/></div><button className="btn" onClick={requestReset} disabled={working||!email.includes("@")}>{working?"Sending…":"Send reset link"}</button></>}
 {error&&<div className="error">{error}</div>}<div className="footerhint">Reset links are one-time and expire after 30 minutes.</div></main></div>
}

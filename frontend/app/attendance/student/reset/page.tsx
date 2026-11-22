"use client";
import {useState} from "react";
import Link from "next/link";
import {ArrowLeft,KeyRound} from "lucide-react";
import {api,json} from "../../lib/api";

export default function ResetPassword({searchParams}:{searchParams:{token?:string}}){
 const token=searchParams.token||"";
 const [password,setPassword]=useState(""),[confirm,setConfirm]=useState(""),[done,setDone]=useState(false),[error,setError]=useState(""),[working,setWorking]=useState(false);
 async function reset(){setError("");if(password!==confirm){setError("The passwords do not match.");return}if(password.length<12||!/[a-z]/.test(password)||!/[A-Z]/.test(password)||!/[0-9]/.test(password)||!/[^A-Za-z0-9]/.test(password)){setError("Use at least 12 characters with uppercase and lowercase letters, a number, and a symbol.");return}setWorking(true);try{await api("/api/phone/password-reset/confirm",json({token,new_password:password}));setDone(true)}catch(e:any){setError(e.message)}finally{setWorking(false)}}
 return <div className="centerpage"><main className="mobilebox"><Link href="/attendance/student" className="muted inline"><ArrowLeft size={14}/> Back to sign in</Link><div className="eyebrow" style={{marginTop:21}}>ACCOUNT SECURITY</div><div className="inline" style={{justifyContent:"space-between"}}><h1>Choose a new password</h1><KeyRound color="#087f89"/></div>
 {!token?<div className="error" style={{marginTop:18}}>This reset link is missing or invalid. Request a new one from the sign-in page.</div>:done?<div className="success" style={{marginTop:18}}>Your password has been reset. You can sign in with the new password now.<Link href="/attendance/student" className="btn" style={{display:"block",textAlign:"center",marginTop:14}}>Return to student sign-in</Link></div>:<><p className="muted">Choose at least 12 characters, including uppercase and lowercase letters, a number, and a symbol.</p><div className="field"><label>NEW PASSWORD</label><input type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 12 characters"/></div><div className="field"><label>CONFIRM NEW PASSWORD</label><input type="password" autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)} placeholder="Enter it again"/></div><button className="btn" onClick={reset} disabled={working||!password||!confirm}>{working?"Updating…":"Reset password"}</button></>}
 {error&&<div className="error">{error}</div>}<div className="footerhint">Reset links expire after 30 minutes and can be used once.</div></main></div>
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Building2, CalendarCheck2, GraduationCap, History, MonitorPlay, Moon, Plus, Smartphone, Sun, Users } from "lucide-react";

type InstructorSidebarProps = { active: "attendance" | "history" | "enroll" | "students" | "remote"; enrollmentHref?: string };

export default function InstructorSidebar({ active, enrollmentHref = "/attendance/enroll" }: InstructorSidebarProps) {
  const [theme, setTheme] = useState<"daylight" | "midnight">("daylight");
  useEffect(() => {
    const saved = window.localStorage.getItem("nexus-attendance-theme");
    if (saved === "daylight" || saved === "midnight") {
      setTheme(saved);
      document.documentElement.setAttribute("data-theme", saved);
      document.querySelector("[data-attendance-root]")?.setAttribute("data-theme", saved);
    }
  }, []);
  function toggleTheme() {
    const next = theme === "daylight" ? "midnight" : "daylight";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    document.querySelector("[data-attendance-root]")?.setAttribute("data-theme", next);
    window.localStorage.setItem("nexus-attendance-theme", next);
  }
  const links = [
    { key: "attendance", label: "Attendance", href: "/attendance", icon: CalendarCheck2 },
    { key: "remote", label: "Remote start", href: "/attendance/remote", icon: MonitorPlay },
    { key: "history", label: "Session history", href: "/attendance/history", icon: History },
    { key: "students", label: "Students", href: "/attendance/students", icon: Users },
    { key: "enroll", label: "Enroll student", href: enrollmentHref, icon: Plus },
  ] as const;
  return <div className="nexus-shell-header">
    <header className="nexus-topbar"><div className="nexus-topbar-inner">
      <Link className="nexus-brand" href="/" aria-label="Return to NEXUS"><span className="nexus-brand-mark"><Building2 size={19} /></span><span className="nexus-brand-copy"><b>NEXUS</b><small>Smart Building Monitor</small></span></Link>
      <span className="nexus-top-divider" />
      <span className="nexus-module-name">Classroom Attendance</span>
      <div className="nexus-header-actions">
        <span className="nexus-live-pill"><i />INSTRUCTOR CONSOLE</span>
        <Link className="nexus-icon-button student-portal-action" href="/attendance/student" aria-label="Student phone page" title="Student phone page"><Smartphone size={16} /></Link>
        <button className="nexus-theme-button" type="button" onClick={toggleTheme}>{theme === "daylight" ? <Moon size={15} /> : <Sun size={15} />}<span>{theme === "daylight" ? "Dark mode" : "Light mode"}</span></button>
      </div>
    </div></header>
    <nav className="nexus-service-bar" aria-label="Classroom attendance tools"><div className="nexus-service-inner"><span className="nexus-service-label"><GraduationCap size={14} />CLASSROOM</span><div className="nexus-service-links">{links.map(({ key, label, href, icon: Icon }) => <Link key={key} className={`nexus-service-link${active === key ? " active" : ""}`} href={href}><Icon size={15} /><span>{label}</span></Link>)}</div></div></nav>
  </div>;
}

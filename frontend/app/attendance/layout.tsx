import "./attendance.css";

export default function AttendanceLayout({ children }: { children: React.ReactNode }) {
  return <div data-attendance-root data-theme="daylight">{children}</div>;
}

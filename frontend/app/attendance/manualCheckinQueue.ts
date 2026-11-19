export type PendingManualCheckin = {
  id: string;
  session_id: string;
  student_id: string;
  reason: string;
  queued_at: string;
};

const STORAGE_KEY = "nexus-attendance-pending-manual-checkins";

export function readPendingManualCheckins(): PendingManualCheckin[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function enqueueManualCheckin(entry: PendingManualCheckin): PendingManualCheckin[] {
  const existing = readPendingManualCheckins();
  const withoutDuplicate = existing.filter(
    item => !(item.session_id === entry.session_id && item.student_id === entry.student_id)
  );
  const next = [...withoutDuplicate, entry];
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function removePendingManualCheckin(id: string): PendingManualCheckin[] {
  const next = readPendingManualCheckins().filter(item => item.id !== id);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { NavLink } from "react-router";
import JobButton from "./jobs/JobButton";

const items = [
  { to: "/", label: "Today" },
  { to: "/progress", label: "Progress" },
  { to: "/nutrition", label: "Nutrition" },
  { to: "/labs", label: "Labs" },
  { to: "/settings", label: "Settings" },
];

export default function AvatarMenu() {
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState({ sync: false, checkin: false });
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const onSync = useCallback((r: boolean) => setRunning((s) => ({ ...s, sync: r })), []);
  const onCheckin = useCallback((r: boolean) => setRunning((s) => ({ ...s, checkin: r })), []);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const busy = running.sync || running.checkin;
  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={busy ? "Account menu, a job is running" : "Account menu"}
        aria-expanded={open}
        aria-controls={panelId}
        className="relative grid h-9 w-9 place-items-center rounded-full bg-accent/15 text-accent hover:bg-accent/25"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden="true">
          <path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm0 2c-4.4 0-8 2.4-8 5.3V21h16v-1.7c0-2.9-3.6-5.3-8-5.3Z" />
        </svg>
        {busy && <span aria-hidden="true" className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 animate-pulse rounded-full bg-accent ring-2 ring-surface-2" />}
      </button>
      {/* Hidden rather than unmounted so a running job keeps its stream and transcript. */}
      <div
        id={panelId}
        hidden={!open}
        className="absolute top-full right-0 z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-surface-2 p-2 shadow-lg"
      >
        <nav aria-label="Sections" className="flex flex-col gap-0.5">
          {items.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.to === "/"}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm ${isActive ? "bg-accent/15 font-medium text-accent" : "text-ink-2 hover:bg-surface hover:text-ink"}`
              }
            >
              {it.label}
            </NavLink>
          ))}
        </nav>
        <div className="my-2 border-t border-line" />
        <div className="flex flex-col gap-2 px-1 pb-1">
          <JobButton kind="sync" label="Sync now" body={{}} onRunning={onSync} />
          <JobButton kind="checkin" label="Weekly check-in" body={{ sync: true }} onRunning={onCheckin} />
        </div>
      </div>
    </div>
  );
}

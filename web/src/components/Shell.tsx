import { useEffect, useRef } from "react";
import { Outlet, useLocation } from "react-router";
import { useToday } from "../api/queries";
import Header from "./Header";
import JobButton from "./jobs/JobButton";
import Tabs from "./shell/Tabs";

export default function Shell() {
  const today = useToday();
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const shown = useRef(pathname);
  // Move focus to the page after navigation (not on first load) so a screen reader starts there.
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    main.current?.focus();
  }, [pathname]);
  return (
    <div className="flex h-full flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface-2 focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to main content
      </a>
      <Header
        today={today.data}
        now={today.dataUpdatedAt || undefined}
        slots={
          <div className="flex items-start gap-2">
            <div className="w-40"><JobButton kind="sync" label="Sync now" body={{}} /></div>
            <div className="w-40"><JobButton kind="checkin" label="Weekly check-in" body={{ sync: true }} /></div>
          </div>
        }
      />
      <Tabs />
      <main id="main" ref={main} tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto focus:outline-none">
        <Outlet />
      </main>
    </div>
  );
}

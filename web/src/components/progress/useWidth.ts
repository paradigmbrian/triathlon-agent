import { useEffect, useRef, useState } from "react";

const DEFAULT_W = 800;
const MIN_W = 280;

/** The drawing width for an SVG chart: the container's width, so one SVG unit is one pixel and 12px axis text stays 12px on a phone. Falls back to 800 before the first measure and where ResizeObserver is missing. */
export function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(DEFAULT_W);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const x = Math.floor(entry.contentRect.width);
      if (x > 0) setW(Math.max(MIN_W, x));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

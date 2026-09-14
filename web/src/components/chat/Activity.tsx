import { useState } from "react";

export default function Activity({ text, args, where }: { text: string; args?: unknown; where: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 text-xs text-ink-2">
      <button type="button" onClick={() => setOpen((o) => !o)} className="font-mono hover:text-ink" aria-expanded={open}>
        {where !== "coach" ? `[${where}] ` : ""}{text}
      </button>
      {open && args !== undefined && (
        <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface p-2 text-[11px]">{JSON.stringify(args, null, 2)}</pre>
      )}
    </div>
  );
}

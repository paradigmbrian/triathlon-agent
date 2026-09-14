import { useState, type FormEvent, type KeyboardEvent } from "react";

export default function Composer({ disabled, hint, onSend }: { disabled: boolean; hint?: string; onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) submit();
  };
  return (
    <form onSubmit={submit} className="border-t border-line bg-surface-2 p-3">
      {hint && <p className="mb-2 text-xs text-warn">{hint}</p>}
      <div className="flex gap-2">
        <textarea
          aria-label="Message"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={disabled}
          rows={2}
          placeholder="Ask your coach"
          className="flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent disabled:opacity-60"
        />
        <button type="submit" disabled={disabled || !text.trim()} className="rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50">
          Send
        </button>
      </div>
    </form>
  );
}

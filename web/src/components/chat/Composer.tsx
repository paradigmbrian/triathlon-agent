import { useState, type FormEvent, type KeyboardEvent } from "react";

type Props = { disabled: boolean; hint?: string; initialText?: string; onSend: (text: string) => void };

export default function Composer({ disabled, hint, initialText = "", onSend }: Props) {
  const [text, setText] = useState(initialText);
  const doSend = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText("");
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    doSend();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  };
  return (
    <form onSubmit={submit} className="border-t border-line bg-surface-2 px-4 py-3">
      <div className="mx-auto w-full max-w-3xl">
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
            className="flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-sm leading-relaxed placeholder:text-ink-2 focus:border-accent focus-visible:outline-offset-0 disabled:opacity-60"
          />
          <button type="submit" disabled={disabled || !text.trim()} className="rounded-md bg-accent px-4 text-sm font-medium text-on-fill disabled:opacity-50">
            Send
          </button>
        </div>
      </div>
    </form>
  );
}

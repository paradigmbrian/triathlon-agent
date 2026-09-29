export default function HoldLine({ count, onGo }: { count: number; onGo: () => void }) {
  const what = count > 0 ? `${count} change${count === 1 ? "" : "s"}` : "a review";
  return (
    <div className="border-b border-line px-6 py-3">
      <button type="button" onClick={onGo} className="inline-flex min-h-8 items-center rounded-md border border-hold/60 px-3 text-sm font-medium text-hold hover:bg-hold/10">
        HOLD · {what} awaiting your approval
      </button>
    </div>
  );
}

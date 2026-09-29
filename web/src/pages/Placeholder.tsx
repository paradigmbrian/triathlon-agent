const blurbs = {
  3: "daily targets, fuel plans and the fuel log",
  4: "lab panels, reports and PDF upload",
};

export default function Placeholder({ name, subProject }: { name: string; subProject: 3 | 4 }) {
  return (
    <section className="mx-auto w-full max-w-4xl px-6 py-6">
      <h1 className="text-sm font-semibold tracking-wide uppercase">{name}</h1>
      <p className="mt-3 border-t border-line pt-3 text-sm text-ink-2">Coming soon: {blurbs[subProject]}.</p>
    </section>
  );
}

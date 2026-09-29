const blurbs = {
  2: "your fitness curve, weekly load by sport and recovery trends",
  3: "daily targets, fuel plans and the fuel log",
  4: "lab panels, reports and PDF upload",
};

export default function Placeholder({ name, subProject }: { name: string; subProject: 2 | 3 | 4 }) {
  return (
    <section className="p-6">
      <h1 className="text-lg font-semibold">{name}</h1>
      <p className="mt-2 text-ink-2">Coming soon: {blurbs[subProject]}.</p>
    </section>
  );
}

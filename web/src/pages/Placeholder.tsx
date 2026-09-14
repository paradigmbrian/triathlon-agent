export default function Placeholder({ name, subProject }: { name: string; subProject: 2 | 3 | 4 }) {
  const spec = { 2: "tri-web progress", 3: "tri-web nutrition", 4: "tri-web labs" }[subProject];
  return (
    <section className="p-6">
      <h1 className="text-lg font-semibold">{name}</h1>
      <p className="mt-2 text-ink-2">
        {name} arrives in sub-project {subProject} ({spec}).
      </p>
    </section>
  );
}

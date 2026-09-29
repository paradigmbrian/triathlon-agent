import MemoryTable from "../components/settings/MemoryTable";
import ResetButton from "../components/settings/ResetButton";
import Readiness from "../components/settings/Readiness";
import Section from "../components/board/Section";

export default function Settings() {
  return (
    <div className="mx-auto w-full max-w-4xl pb-10">
      <h1 className="px-6 pt-6 text-sm font-semibold tracking-wide uppercase">Settings</h1>
      <Section title="Coach memory"><MemoryTable /></Section>
      <Section title="Reset"><ResetButton /></Section>
      <Section title="Readiness"><Readiness /></Section>
    </div>
  );
}

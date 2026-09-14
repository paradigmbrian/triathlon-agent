import MemoryTable from "../components/settings/MemoryTable";
import ResetButton from "../components/settings/ResetButton";
import Readiness from "../components/settings/Readiness";

export default function Settings() {
  return (
    <section className="space-y-8 p-6">
      <div>
        <h1 className="text-lg font-semibold">Coach memory</h1>
        <div className="mt-2"><MemoryTable /></div>
      </div>
      <div>
        <h2 className="text-lg font-semibold">Reset</h2>
        <div className="mt-2"><ResetButton /></div>
      </div>
      <div>
        <h2 className="text-lg font-semibold">Readiness</h2>
        <div className="mt-2"><Readiness /></div>
      </div>
    </section>
  );
}

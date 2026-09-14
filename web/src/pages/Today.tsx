import Header from "../components/Header";
import { useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  return (
    <>
      <Header today={today.data} />
      <section className="p-4">Today (Task 4)</section>
    </>
  );
}

import Header from "../components/Header";
import Strip from "../components/today/Strip";
import { useToday } from "../api/queries";

export default function Today() {
  const today = useToday();
  return (
    <>
      <Header today={today.data} />
      <Strip today={today.data} />
    </>
  );
}

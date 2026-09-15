import { Outlet } from "react-router";
import { useToday } from "../api/queries";
import AvatarMenu from "./AvatarMenu";
import Header from "./Header";

export default function Shell() {
  const today = useToday();
  return (
    <div className="flex h-full flex-col">
      <Header today={today.data} slots={<AvatarMenu />} />
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

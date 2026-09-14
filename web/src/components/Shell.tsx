import { Outlet } from "react-router";
import Rail from "./Rail";

export default function Shell() {
  return (
    <div className="flex h-full flex-col md:flex-row">
      <Rail />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto pb-14 md:pb-0">
        <Outlet />
      </div>
    </div>
  );
}

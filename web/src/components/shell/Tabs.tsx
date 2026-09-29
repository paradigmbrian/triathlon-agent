import { NavLink } from "react-router";

const items = [
  { to: "/", label: "Today" },
  { to: "/progress", label: "Progress" },
  { to: "/nutrition", label: "Nutrition" },
  { to: "/labs", label: "Labs" },
  { to: "/settings", label: "Settings" },
];

export default function Tabs() {
  return (
    <nav aria-label="Sections" className="flex shrink-0 gap-1 overflow-x-auto border-b border-line bg-surface-2 px-4">
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === "/"}
          className={({ isActive }) =>
            `-mb-px inline-flex min-h-10 items-center border-b-2 px-3 text-sm whitespace-nowrap ${
              isActive ? "border-hold font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`
          }
        >
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}

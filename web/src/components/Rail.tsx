import { NavLink } from "react-router";

const items = [
  { to: "/", label: "Today" },
  { to: "/progress", label: "Progress" },
  { to: "/nutrition", label: "Nutrition" },
  { to: "/labs", label: "Labs" },
  { to: "/settings", label: "Settings" },
];

export default function Rail() {
  return (
    <nav
      aria-label="Sections"
      className="fixed inset-x-0 bottom-0 z-10 flex justify-around border-t border-line bg-surface-2 md:static md:h-full md:w-44 md:flex-col md:justify-start md:gap-1 md:border-r md:border-t-0 md:p-3"
    >
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === "/"}
          className={({ isActive }) =>
            `rounded-md px-3 py-2 text-sm ${isActive ? "bg-accent/15 font-medium text-accent" : "text-ink-2 hover:text-ink"}`
          }
        >
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}

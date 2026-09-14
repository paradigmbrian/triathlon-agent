import { createBrowserRouter } from "react-router";
import Shell from "./components/Shell";
import Today from "./pages/Today";
import Settings from "./pages/Settings";
import Placeholder from "./pages/Placeholder";

export const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: "/", element: <Today /> },
      { path: "/progress", element: <Placeholder name="Progress" subProject={2} /> },
      { path: "/nutrition", element: <Placeholder name="Nutrition" subProject={3} /> },
      { path: "/labs", element: <Placeholder name="Labs" subProject={4} /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);

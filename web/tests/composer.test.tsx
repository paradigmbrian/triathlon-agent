import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Composer from "../src/components/chat/Composer";

test("Enter submits the trimmed text and clears the composer", async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();
  render(<Composer disabled={false} onSend={onSend} />);
  const box = screen.getByLabelText("Message");
  await user.type(box, "  hello  ");
  await user.keyboard("{Enter}");
  expect(onSend).toHaveBeenCalledTimes(1);
  expect(onSend).toHaveBeenCalledWith("hello");
  expect(box).toHaveValue("");
});

test("Shift+Enter inserts a newline instead of submitting", async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();
  render(<Composer disabled={false} onSend={onSend} />);
  const box = screen.getByLabelText("Message");
  await user.type(box, "line one");
  await user.keyboard("{Shift>}{Enter}{/Shift}");
  expect(onSend).not.toHaveBeenCalled();
  expect(box).toHaveValue("line one\n");
});

test("disabled blocks submit", () => {
  const onSend = vi.fn();
  render(<Composer disabled onSend={onSend} />);
  const box = screen.getByLabelText("Message");
  expect(box).toBeDisabled();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  fireEvent.change(box, { target: { value: "hello" } });
  fireEvent.submit(box.closest("form")!);
  expect(onSend).not.toHaveBeenCalled();
});

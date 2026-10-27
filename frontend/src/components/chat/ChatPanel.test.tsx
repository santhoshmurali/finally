import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "@/test/factories";
import { ChatPanel } from "./ChatPanel";

const history = [
  { role: "user", content: "How is my book?", actions: null, created_at: "2026-10-27T09:00:00Z" },
  {
    role: "assistant",
    content: "Mostly TCS.",
    actions: null,
    created_at: "2026-10-27T09:00:01Z",
  },
];

const reply = {
  message: "Bought 1 TCS (mock reply).",
  trades: [{ id: "t1", ticker: "TCS", side: "buy", quantity: 1, price: 2529, executed_at: "t" }],
  watchlist_changes: [{ ticker: "WIPRO", action: "add" }],
};

function routeFetch(chatResponse: Promise<Response> | Response) {
  vi.mocked(fetch).mockImplementation((input) => {
    if (String(input) === "/api/chat/history") return Promise.resolve(jsonResponse(history));
    return Promise.resolve(chatResponse as Response);
  });
}

async function sendMessage(text: string) {
  fireEvent.change(screen.getByTestId("chat-input"), { target: { value: text } });
  fireEvent.click(screen.getByTestId("chat-send"));
}

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the stored conversation history on load", async () => {
    routeFetch(jsonResponse(reply));
    render(<ChatPanel onReply={vi.fn()} />);

    const messages = await screen.findAllByTestId("chat-message");
    expect(messages).toHaveLength(2);
    expect(messages[0]).toHaveAttribute("data-role", "user");
    expect(screen.getByText("Mostly TCS.")).toBeInTheDocument();
  });

  it("shows a loading indicator while the reply is pending, then the reply with inline confirmations", async () => {
    let resolveReply: (response: Response) => void = () => undefined;
    routeFetch(new Promise<Response>((resolve) => (resolveReply = resolve)));
    const onReply = vi.fn();
    render(<ChatPanel onReply={onReply} />);
    await screen.findAllByTestId("chat-message");

    await sendMessage("buy a TCS");
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByTestId("chat-input")).toBeDisabled();

    resolveReply(jsonResponse(reply));
    await waitFor(() => expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument());

    expect(screen.getByText("Bought 1 TCS (mock reply).")).toBeInTheDocument();
    expect(screen.getByTestId("chat-trade")).toHaveTextContent("buy 1 TCS @ ₹2,529.00");
    expect(screen.getByTestId("chat-watchlist-change")).toHaveTextContent("Added WIPRO to watchlist");
    expect(onReply).toHaveBeenCalledTimes(1);
  });

  it("posts the trimmed message as JSON", async () => {
    routeFetch(jsonResponse(reply));
    render(<ChatPanel onReply={vi.fn()} />);
    await screen.findAllByTestId("chat-message");

    await sendMessage("  buy a TCS  ");

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/chat",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "buy a TCS" }) }),
      ),
    );
  });

  it("shows the error and keeps the draft when the assistant is unavailable", async () => {
    routeFetch(jsonResponse({ detail: "LLM unavailable" }, 502));
    const onReply = vi.fn();
    render(<ChatPanel onReply={onReply} />);
    await screen.findAllByTestId("chat-message");

    await sendMessage("hello");

    expect(await screen.findByTestId("chat-error")).toHaveTextContent("LLM unavailable");
    expect(screen.getByTestId("chat-input")).toHaveValue("hello");
    expect(onReply).not.toHaveBeenCalled();
  });

  it("collapses to a narrow strip and expands again", async () => {
    routeFetch(jsonResponse(reply));
    render(<ChatPanel onReply={vi.fn()} />);
    await screen.findAllByTestId("chat-message");

    fireEvent.click(screen.getByTestId("chat-toggle"));
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-collapsed", "true");
    expect(within(screen.getByTestId("chat-panel")).queryByTestId("chat-input")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("chat-toggle"));
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });
});

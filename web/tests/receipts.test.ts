import { beforeEach, describe, expect, it, vi } from "vitest";

// The store talks to the API on flush. Stub the transport so these tests are
// about the receipt RULES, not about HTTP.
const acked: Array<{ token: string; tickers: string[] }> = [];
const keepalives: Array<{ token: string; tickers: string[] }> = [];
const feedbacks: unknown[][] = [];

vi.mock("@/lib/api", () => ({
  ack: async (token: string, tickers?: string[]) => {
    acked.push({ token, tickers: tickers ?? [] });
    return {
      results: Object.fromEntries((tickers ?? []).map((t) => [t, "applied"])),
    };
  },
  ackKeepalive: (token: string, tickers: string[]) => {
    keepalives.push({ token, tickers });
  },
  sendFeedback: async (events: unknown[]) => {
    feedbacks.push(events);
  },
}));

const { useReceipts } = await import("@/lib/receipts");

const reset = () => {
  acked.length = 0;
  keepalives.length = 0;
  feedbacks.length = 0;
  useReceipts.setState({
    armed: false,
    token: "tok",
    pending: new Set(),
    acked: new Set(),
    feedback: [],
    lastResults: {},
  });
};

describe("read receipts", () => {
  beforeEach(reset);

  it("acks nothing when the page has only been loaded", async () => {
    // The observer is gated on `armed`, which no amount of rendering sets.
    // This is the whole acceptance criterion: loading a digest with every card
    // on screen and touching nothing must acknowledge nothing.
    expect(useReceipts.getState().armed).toBe(false);
    await useReceipts.getState().flush(false);
    expect(acked).toHaveLength(0);
    expect(useReceipts.getState().pending.size).toBe(0);
  });

  it("arms once, on the first interaction, and stays armed", () => {
    useReceipts.getState().arm();
    expect(useReceipts.getState().armed).toBe(true);
    useReceipts.getState().arm();
    expect(useReceipts.getState().armed).toBe(true);
  });

  it("never auto-acks a critical card", async () => {
    const s = useReceipts.getState();
    s.arm();
    s.markRead("NVDA", "critical");
    s.markRead("AAPL", "notable");

    expect([...useReceipts.getState().pending]).toEqual(["AAPL"]);
    await useReceipts.getState().flush(false);
    expect(acked[0].tickers).toEqual(["AAPL"]);
  });

  it("clears a critical only on an explicit dismissal", async () => {
    const s = useReceipts.getState();
    s.arm();
    s.markRead("NVDA", "critical");
    expect(useReceipts.getState().pending.size).toBe(0);

    useReceipts.getState().dismiss("NVDA", "critical", 4.2, false);
    expect([...useReceipts.getState().pending]).toEqual(["NVDA"]);
    await useReceipts.getState().flush(false);
    expect(acked[0].tickers).toEqual(["NVDA"]);
  });

  it("does not queue the same ticker twice", () => {
    const s = useReceipts.getState();
    s.arm();
    s.markRead("AAPL", "minor");
    useReceipts.getState().markRead("AAPL", "minor");
    expect(useReceipts.getState().pending.size).toBe(1);
  });

  it("keeps a not_found receipt pending instead of dropping it", async () => {
    const { useReceipts: store } = await import("@/lib/receipts");
    store.setState({ token: "tok", pending: new Set(["GONE"]) });

    // A transient race must not silently lose the receipt.
    const original = (await import("@/lib/api")).ack;
    const mod = await import("@/lib/api");
    (mod as { ack: unknown }).ack = async () => ({
      results: { GONE: "not_found" as const },
    });
    await store.getState().flush(false);
    (mod as { ack: unknown }).ack = original;

    expect([...store.getState().pending]).toEqual(["GONE"]);
    expect(store.getState().acked.has("GONE")).toBe(false);
  });

  it("flushes through keepalive when the tab is going away", async () => {
    const s = useReceipts.getState();
    s.arm();
    s.markRead("MSFT", "minor");
    await useReceipts.getState().flush(true);

    // `sendBeacon` cannot set an Authorization header, so this path is a
    // keepalive fetch rather than a beacon.
    expect(keepalives).toHaveLength(1);
    expect(keepalives[0].tickers).toEqual(["MSFT"]);
    expect(acked).toHaveLength(0);
    expect(useReceipts.getState().pending.size).toBe(0);
  });

  it("does nothing without a digest token", async () => {
    useReceipts.setState({ token: null, pending: new Set(["AAPL"]) });
    await useReceipts.getState().flush(false);
    expect(acked).toHaveLength(0);
  });

  it("records feedback separately from acks", async () => {
    const s = useReceipts.getState();
    s.thumb("NVDA", "critical", 4.2, 1);
    s.clickThrough("AMD", "notable", 2.1);
    await useReceipts.getState().flush(false);

    expect(feedbacks[0]).toHaveLength(2);
    expect(acked).toHaveLength(0);
  });
});

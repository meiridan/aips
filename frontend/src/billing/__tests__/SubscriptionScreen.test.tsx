import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import type { Plan, Subscription } from "../../types";
import SubscriptionScreen from "../SubscriptionScreen";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    fetchPlans: vi.fn(),
    fetchSubscription: vi.fn(),
    startCheckout: vi.fn(),
    openBillingPortal: vi.fn(),
  };
});

const api = await import("../../api");
const fetchPlans = vi.mocked(api.fetchPlans);
const fetchSubscription = vi.mocked(api.fetchSubscription);
const startCheckout = vi.mocked(api.startCheckout);
const openBillingPortal = vi.mocked(api.openBillingPortal);

const strings = new Proxy({} as Record<string, string>, {
  get: (_t, key: string) => `[${key}]`,
  has: () => true,
});

const PLANS: Plan[] = [
  {
    id: "free",
    he: "חינם",
    description: "free plan",
    price: 0,
    currency: "ILS",
    interval: null,
    features: ["a limited chat"],
  },
  {
    id: "plus_monthly",
    he: "פלוס",
    description: "paid plan",
    price: 39,
    currency: "ILS",
    interval: "month",
    features: ["unlimited", "long memory"],
  },
];

const FREE: Subscription = {
  plan_id: "free",
  status: "inactive",
  current_period_end: null,
  cancel_at_period_end: false,
  manageable: false,
};

const PAID: Subscription = {
  plan_id: "plus_monthly",
  status: "active",
  current_period_end: "2030-01-15T00:00:00+00:00",
  cancel_at_period_end: false,
  manageable: true,
};

beforeEach(() => {
  fetchPlans.mockResolvedValue({ plans: PLANS });
  fetchSubscription.mockResolvedValue(FREE);
});

afterEach(cleanup);

function renderScreen(justReturned = false) {
  render(
    <SubscriptionScreen
      strings={strings}
      justReturnedFromCheckout={justReturned}
      onLogout={() => {}}
    />,
  );
}

describe("rendering", () => {
  it("hides the logout button in single-user mode", async () => {
    // No onLogout: the server reported auth.single_user, so there is no session
    // to end and the button would lead to an unreachable login screen.
    render(<SubscriptionScreen strings={strings} justReturnedFromCheckout={false} />);
    await waitFor(() => expect(screen.getByText("פלוס")).toBeTruthy());
    expect(screen.queryByText("[logout]")).toBeNull();
  });

  it("shows a spinner until both requests land", () => {
    fetchPlans.mockReturnValue(new Promise(() => {}));
    renderScreen();
    expect(document.querySelector(".spinner")).toBeTruthy();
  });

  it("lists every plan with price and features", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByText("פלוס")).toBeTruthy());
    expect(screen.getByText("₪39 [per_month]")).toBeTruthy();
    expect(screen.getByText("[free_forever]")).toBeTruthy();
    expect(screen.getByText("unlimited")).toBeTruthy();
  });

  it("badges the current plan and offers no button for it", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByText("[plan_current_badge]")).toBeTruthy());
    // Free is current, so only the paid plan has a call to action.
    expect(screen.getAllByRole("button", { name: "[plan_select]" })).toHaveLength(1);
  });

  it("shows the renewal date for a subscriber", async () => {
    fetchSubscription.mockResolvedValue(PAID);
    renderScreen();
    await waitFor(() => expect(screen.getByText(/\[subscription_renews\]/)).toBeTruthy());
    expect(screen.getByRole("button", { name: "[subscription_manage]" })).toBeTruthy();
  });

  it("says so when the subscription is set to end", async () => {
    fetchSubscription.mockResolvedValue({ ...PAID, cancel_at_period_end: true });
    renderScreen();
    await waitFor(() => expect(screen.getByText("[subscription_canceling]")).toBeTruthy());
    expect(screen.getByText(/\[subscription_ends\]/)).toBeTruthy();
  });

  it("hides the manage button with no billing account", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByText("פלוס")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "[subscription_manage]" })).toBeNull();
  });
});

describe("choosing a plan", () => {
  it("sends the browser to Stripe", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });
    startCheckout.mockResolvedValue({ url: "https://checkout.stripe.com/c/pay/cs_1" });

    renderScreen();
    await waitFor(() => expect(screen.getByRole("button", { name: "[plan_select]" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "[plan_select]" }));

    await waitFor(() => expect(startCheckout).toHaveBeenCalledWith("plus_monthly"));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_1"));
  });

  it("shows a busy state and blocks a second click", async () => {
    startCheckout.mockReturnValue(new Promise(() => {}));
    renderScreen();
    await waitFor(() => expect(screen.getByRole("button", { name: "[plan_select]" })).toBeTruthy());

    const button = screen.getByRole("button", { name: "[plan_select]" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "[plan_selecting]" })).toBeTruthy(),
    );
    expect(startCheckout).toHaveBeenCalledTimes(1);
  });

  it("reports billing being unavailable", async () => {
    startCheckout.mockRejectedValue(new ApiError(503, "billing_unavailable"));
    renderScreen();
    await waitFor(() => expect(screen.getByRole("button", { name: "[plan_select]" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "[plan_select]" }));
    await waitFor(() => expect(screen.getByText("[billing_unavailable]")).toBeTruthy());
  });

  it("offers an upgrade rather than a purchase to an existing subscriber", async () => {
    fetchSubscription.mockResolvedValue({ ...PAID, plan_id: "free", manageable: true });
    fetchPlans.mockResolvedValue({
      plans: [
        ...PLANS,
        {
          id: "plus_yearly",
          he: "שנתי",
          description: "yearly",
          price: 390,
          currency: "ILS",
          interval: "year",
          features: [],
        },
      ],
    });
    renderScreen();
    await waitFor(() => expect(screen.getByText("שנתי")).toBeTruthy());
    expect(screen.getByText("₪390 [per_year]")).toBeTruthy();
  });
});

describe("the portal", () => {
  it("sends the browser to Stripe's billing portal", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign },
      writable: true,
    });
    fetchSubscription.mockResolvedValue(PAID);
    openBillingPortal.mockResolvedValue({ url: "https://billing.stripe.com/p/session/1" });

    renderScreen();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "[subscription_manage]" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "[subscription_manage]" }));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://billing.stripe.com/p/session/1"),
    );
  });
});

describe("errors", () => {
  it("shows a message when the subscription cannot be loaded", async () => {
    fetchSubscription.mockRejectedValue(new ApiError(500, "boom"));
    renderScreen();
    await waitFor(() => expect(screen.getByText("[subscription_error]")).toBeTruthy());
  });

  it("stays quiet on a 401, which the session handles globally", async () => {
    fetchSubscription.mockRejectedValue(new ApiError(401, "not_authenticated"));
    renderScreen();
    await waitFor(() => expect(document.querySelector(".spinner")).toBeTruthy());
    expect(screen.queryByText("[subscription_error]")).toBeNull();
  });
});

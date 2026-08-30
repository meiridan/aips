import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchPlans, fetchSubscription, openBillingPortal, startCheckout } from "../api";
import { ROUTES, navigate } from "../router";
import type { Plan, Subscription } from "../types";

interface Props {
  strings: Record<string, string>;
  /** ?checkout=success — the webhook may land a moment after the redirect. */
  justReturnedFromCheckout: boolean;
  onLogout: () => void;
}

const FREE_PLAN_ID = "free";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("he-IL", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function price(plan: Plan, s: Record<string, string>): string {
  if (plan.price === 0) return s.free_forever;
  const suffix = plan.interval === "year" ? s.per_year : s.per_month;
  return `₪${plan.price} ${suffix}`;
}

export default function SubscriptionScreen({
  strings: s,
  justReturnedFromCheckout,
  onLogout,
}: Props) {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyPlan, setBusyPlan] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      // Same parallel-fetch shape the app already uses at boot.
      const [{ plans }, current] = await Promise.all([fetchPlans(), fetchSubscription()]);
      setPlans(plans);
      setSubscription(current);
      return current;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return null; // handled globally
      setError(s.subscription_error);
      return null;
    }
  }, [s.subscription_error]);

  useEffect(() => {
    void load();
  }, [load]);

  // Stripe redirects back before its webhook necessarily has; poll briefly so
  // the screen doesn't show "free" to someone who just paid.
  useEffect(() => {
    if (!justReturnedFromCheckout) return;
    let attempts = 0;
    const timer = setInterval(async () => {
      attempts += 1;
      const current = await load();
      if (attempts >= 5 || (current && current.plan_id !== FREE_PLAN_ID)) {
        clearInterval(timer);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [justReturnedFromCheckout, load]);

  async function choose(planId: string) {
    if (busyPlan) return;
    setBusyPlan(planId);
    setError(null);
    try {
      const { url } = await startCheckout(planId);
      window.location.assign(url);
    } catch (err) {
      const key = err instanceof ApiError ? err.detail : "subscription_error";
      setError(s[key] ?? s.subscription_error);
      setBusyPlan(null);
    }
  }

  async function manage() {
    if (busyPlan) return;
    setBusyPlan("__portal__");
    setError(null);
    try {
      const { url } = await openBillingPortal();
      window.location.assign(url);
    } catch (err) {
      const key = err instanceof ApiError ? err.detail : "subscription_error";
      setError(s[key] ?? s.subscription_error);
      setBusyPlan(null);
    }
  }

  if (!plans || !subscription) {
    return (
      <div className="center-state">
        {error ? <p className="form-error">{error}</p> : <div className="spinner" />}
      </div>
    );
  }

  const currentPlan = plans.find((p) => p.id === subscription.plan_id);
  const isPaid = subscription.plan_id !== FREE_PLAN_ID;

  return (
    <div className="billing">
      <header className="billing-header">
        <button type="button" className="header-link" onClick={() => navigate(ROUTES.chat)}>
          <span className="chev">›</span>
          {s.continue_to_chat}
        </button>
        <button type="button" className="header-link" onClick={onLogout}>
          {s.logout}
        </button>
      </header>

      <h1 className="billing-title">{s.subscription_title}</h1>

      <section className="billing-status">
        <div className="k">{s.subscription_current}</div>
        <div className="v">{currentPlan ? currentPlan.he : s.subscription_none}</div>
        {isPaid && subscription.current_period_end && (
          <div className="billing-renews">
            {subscription.cancel_at_period_end
              ? `${s.subscription_ends}${formatDate(subscription.current_period_end)}`
              : `${s.subscription_renews}${formatDate(subscription.current_period_end)}`}
          </div>
        )}
        {subscription.cancel_at_period_end && (
          <p className="form-warning">{s.subscription_canceling}</p>
        )}
        {subscription.manageable && (
          <button
            type="button"
            className="btn btn-ghost billing-manage"
            disabled={busyPlan !== null}
            onClick={manage}
          >
            {s.subscription_manage}
          </button>
        )}
      </section>

      {error && <p className="form-error">{error}</p>}

      <div className="plan-grid">
        {plans.map((plan) => {
          const isCurrent = plan.id === subscription.plan_id;
          const isFree = plan.id === FREE_PLAN_ID;
          return (
            <article key={plan.id} className={`plan-card ${isCurrent ? "current" : ""}`}>
              {isCurrent && <div className="plan-badge">{s.plan_current_badge}</div>}
              <h2>{plan.he}</h2>
              <div className="plan-price">{price(plan, s)}</div>
              <p className="plan-description">{plan.description}</p>
              <ul className="plan-features">
                {plan.features.map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
              {!isFree && !isCurrent && (
                <button
                  type="button"
                  className="btn btn-primary plan-cta"
                  disabled={busyPlan !== null}
                  onClick={() => choose(plan.id)}
                >
                  {busyPlan === plan.id
                    ? s.plan_selecting
                    : isPaid
                      ? s.plan_upgrade
                      : s.plan_select}
                </button>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

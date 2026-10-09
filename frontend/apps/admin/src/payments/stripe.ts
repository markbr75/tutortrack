/** Loads Stripe.js from js.stripe.com (required for PCI SAQ-A: card fields live in
 * Stripe's iframes, never in our page). Only the calls we use are typed. */

export interface StripeElement {
  mount: (selector: string | HTMLElement) => void;
  destroy: () => void;
}

export interface StripeElements {
  create: (type: "payment", options?: Record<string, unknown>) => StripeElement;
}

export interface StripeResult {
  error?: { message?: string };
  paymentIntent?: { id: string; status: string };
  setupIntent?: { id: string; status: string };
}

export interface StripeClient {
  elements: (options: {
    clientSecret: string;
    appearance?: Record<string, unknown>;
  }) => StripeElements;
  confirmPayment: (options: {
    elements: StripeElements;
    redirect: "if_required";
    confirmParams: { return_url: string };
  }) => Promise<StripeResult>;
  confirmSetup: (options: {
    elements: StripeElements;
    redirect: "if_required";
    confirmParams: { return_url: string };
  }) => Promise<StripeResult>;
}

type StripeFactory = (key: string, options?: { stripeAccount?: string }) => StripeClient;

declare global {
  interface Window {
    Stripe?: StripeFactory;
  }
}

const SRC = "https://js.stripe.com/v3/";
let loading: Promise<StripeFactory> | null = null;

function loadScript(): Promise<StripeFactory> {
  if (window.Stripe) return Promise.resolve(window.Stripe);
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SRC;
    script.async = true;
    script.onload = () => (window.Stripe ? resolve(window.Stripe) : reject(new Error("Stripe")));
    script.onerror = () => {
      loading = null;
      reject(new Error("Stripe.js could not be loaded"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

/** A Stripe client acting on the organisation's connected account. */
export async function stripeFor(publishableKey: string, account: string): Promise<StripeClient> {
  const factory = await loadScript();
  return factory(publishableKey, { stripeAccount: account });
}

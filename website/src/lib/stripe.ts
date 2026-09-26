import Stripe from "stripe";

/**
 * Server-only — never import this in client components.
 *
 * Cloudflare Workers has no Node HTTP stack, so the SDK's default client can't
 * reach Stripe at all ("An error occurred with our connection to Stripe").
 * Both overrides below are what make the SDK work in that runtime: fetch for
 * requests, and WebCrypto for verifying webhook signatures.
 */
export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2025-02-24.acacia",
  httpClient: Stripe.createFetchHttpClient(),
});

/**
 * Webhook signature verification must be async on Workers — the synchronous
 * `constructEvent` needs Node's crypto module. Use it with
 * `stripe.webhooks.constructEventAsync`.
 */
export const webhookCryptoProvider = Stripe.createSubtleCryptoProvider();

export { formatPrice } from "@/lib/format";

/**
 * Lulu Print API client
 *
 * Lulu (https://developers.lulu.com) prints and ships every order. This module
 * is the raw API layer: OAuth tokens and the endpoints we call. The order-shaped
 * wrapper the webhook uses lives in `lib/print.ts`.
 *
 * Auth is OpenID Connect client credentials: a client key/secret pair is
 * exchanged for a short-lived bearer token, which we cache until it expires.
 *
 * Set LULU_API_URL to https://api.sandbox.lulu.com to work against the sandbox,
 * which never sends anything to a real printer. Sandbox credentials are separate
 * from production ones (developers.sandbox.lulu.com).
 */

const DEFAULT_API_URL = "https://api.lulu.com";

/** Lulu's OAuth realm path, identical on production and sandbox. */
const TOKEN_PATH = "/auth/realms/glasstree/protocol/openid-connect/token";

export type LuluShippingLevel =
  | "MAIL"
  | "PRIORITY_MAIL"
  | "GROUND_HD"
  | "GROUND_BUS"
  | "GROUND"
  | "EXPEDITED"
  | "EXPRESS";

export type LuluShippingAddress = {
  name: string;
  street1: string;
  street2?: string;
  city: string;
  state_code?: string;
  country_code: string;
  postcode: string;
  phone_number: string;
  email: string;
};

export type LuluLineItem = {
  title: string;
  quantity: number;
  external_id?: string;
  printable_normalization: {
    pod_package_id: string;
    interior: { source_url: string };
    cover: { source_url: string };
  };
};

export type LuluPrintJobRequest = {
  contact_email: string;
  external_id?: string;
  line_items: LuluLineItem[];
  shipping_address: LuluShippingAddress;
  shipping_level: LuluShippingLevel;
  /** Minutes Lulu waits before production, leaving a cancellation window (60–2880) */
  production_delay?: number;
};

export type LuluPrintJobStatus = {
  name:
    | "CREATED"
    | "UNPAID"
    | "PAYMENT_IN_PROGRESS"
    | "PRODUCTION_DELAYED"
    | "PRODUCTION_READY"
    | "IN_PRODUCTION"
    | "SHIPPED"
    | "REJECTED"
    | "CANCELED";
  message?: string;
  changed?: string;
};

export type LuluPrintJob = {
  id: number;
  external_id?: string;
  status: LuluPrintJobStatus;
  estimated_shipping_dates?: {
    dispatch_min?: string;
    dispatch_max?: string;
    arrival_min?: string;
    arrival_max?: string;
  };
  line_items?: Array<{
    id: number;
    external_id?: string;
    title?: string;
    status?: { name: string; messages?: Record<string, unknown> };
  }>;
};

/** A line item as it comes back on a print job, including shipment details. */
export type LuluLineItemStatus = {
  id?: number;
  external_id?: string;
  title?: string;
  status?: {
    name: string;
    messages?: {
      tracking_id?: string;
      tracking_urls?: string[] | string;
      carrier_name?: string;
      [key: string]: unknown;
    };
  };
};

/** A quote request: what would these books cost to print and ship here? */
export type LuluCostCalculationRequest = {
  line_items: Array<{ page_count: number; pod_package_id: string; quantity: number }>;
  shipping_address: Omit<LuluShippingAddress, "email">;
  shipping_option: LuluShippingLevel;
};

/** Lulu's money amounts are decimal strings, e.g. "7.69". */
type LuluCost = { total_cost_excl_tax: string; total_cost_incl_tax: string };

export type LuluCostCalculation = {
  currency: string;
  line_item_costs: LuluCost[];
  shipping_cost: LuluCost;
  fulfillment_cost: LuluCost;
  /** Sales tax/VAT Lulu charges on the whole job: books, shipping and fee */
  total_tax: string;
};

/** Payload Lulu posts for the PRINT_JOB_STATUS_CHANGED topic. */
export type LuluWebhookPayload = {
  topic: string;
  data: LuluPrintJob & { line_items?: LuluLineItemStatus[] };
};

export class LuluApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: string
  ) {
    super(message);
    this.name = "LuluApiError";
  }
}

function apiUrl(path: string): string {
  const base = (process.env.LULU_API_URL || DEFAULT_API_URL).replace(/\/$/, "");
  return `${base}${path}`;
}

// Tokens last an hour; hold one per isolate rather than re-authenticating per call.
let cachedToken: { value: string; expiresAt: number } | null = null;

async function getAccessToken(): Promise<string> {
  const now = Date.now();
  if (cachedToken && cachedToken.expiresAt > now) return cachedToken.value;

  const key = process.env.LULU_CLIENT_KEY;
  const secret = process.env.LULU_CLIENT_SECRET;
  if (!key || !secret) {
    throw new Error(
      "LULU_CLIENT_KEY and LULU_CLIENT_SECRET must be set to send print jobs to Lulu"
    );
  }

  const res = await fetch(apiUrl(TOKEN_PATH), {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${Buffer.from(`${key}:${secret}`).toString("base64")}`,
    },
    body: "grant_type=client_credentials",
  });

  const body = await res.text();
  if (!res.ok) {
    throw new LuluApiError(`Lulu auth failed (${res.status})`, res.status, body);
  }

  const data = JSON.parse(body) as { access_token: string; expires_in: number };
  // Refresh a minute early so a token can't expire mid-flight.
  cachedToken = {
    value: data.access_token,
    expiresAt: now + Math.max(0, data.expires_in - 60) * 1000,
  };
  return cachedToken.value;
}

async function luluFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  });

  const body = await res.text();
  if (!res.ok) {
    throw new LuluApiError(
      `Lulu API ${init?.method ?? "GET"} ${path} failed (${res.status}): ${body}`,
      res.status,
      body
    );
  }
  return JSON.parse(body) as T;
}

/**
 * Submit a print job. Lulu downloads the interior and cover PDFs from the URLs
 * given, so both must be reachable without authentication for long enough to be
 * fetched and normalized — see `signedFileUrl` in lib/storage.ts.
 *
 * A created job sits in UNPAID until it is paid. Put a card on file in the Lulu
 * developer portal and jobs move to production automatically.
 */
export function createLuluPrintJob(job: LuluPrintJobRequest): Promise<LuluPrintJob> {
  return luluFetch<LuluPrintJob>("/print-jobs/", {
    method: "POST",
    body: JSON.stringify(job),
  });
}

/** Quote a print job without creating one — nothing is ordered or charged. */
export function calculateLuluCost(
  request: LuluCostCalculationRequest
): Promise<LuluCostCalculation> {
  return luluFetch<LuluCostCalculation>("/print-job-cost-calculations/", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function getLuluPrintJob(printJobId: string | number): Promise<LuluPrintJob> {
  return luluFetch<LuluPrintJob>(`/print-jobs/${printJobId}/`);
}

/** Most recent print jobs first — what the developer portal's order list shows. */
export function listLuluPrintJobs(pageSize = 10): Promise<{
  count: number;
  results: LuluPrintJob[];
}> {
  const query = new URLSearchParams({
    page_size: String(pageSize),
    ordering: "-id",
    exclude_line_items: "false",
  });
  return luluFetch(`/print-jobs/?${query}`);
}

/**
 * Verify a webhook Lulu sent us.
 *
 * Lulu signs the raw body with HMAC-SHA256 keyed on the API secret and sends
 * the hex digest in `Lulu-HMAC-SHA256`. WebCrypto rather than node:crypto so
 * this works in the Workers runtime.
 */
export async function verifyLuluWebhook(
  rawBody: string,
  signature: string | null
): Promise<boolean> {
  const secret = process.env.LULU_CLIENT_SECRET;
  if (!secret || !signature) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody));
  const expected = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");

  // Constant-time-ish compare: same length, no early exit on first difference
  const given = signature.trim().toLowerCase();
  if (given.length !== expected.length) return false;
  let mismatch = 0;
  for (let i = 0; i < expected.length; i++) {
    mismatch |= expected.charCodeAt(i) ^ given.charCodeAt(i);
  }
  return mismatch === 0;
}

/**
 * Cancel a print job. Lulu only allows this before production starts —
 * CREATED, UNPAID and PRODUCTION_DELAYED can be canceled, PRODUCTION_READY and
 * anything later cannot.
 */
export function cancelLuluPrintJob(printJobId: string | number): Promise<LuluPrintJobStatus> {
  return luluFetch<LuluPrintJobStatus>(`/print-jobs/${printJobId}/status/`, {
    method: "PUT",
    body: JSON.stringify({ name: "CANCELED" }),
  });
}

export function listLuluWebhooks(): Promise<{
  results: Array<{ id: string; url: string; topics: string[]; is_active: boolean }>;
}> {
  return luluFetch("/webhooks/");
}

export function createLuluWebhook(url: string): Promise<{
  id: string;
  url: string;
  topics: string[];
  is_active: boolean;
}> {
  return luluFetch("/webhooks/", {
    method: "POST",
    body: JSON.stringify({ url, topics: ["PRINT_JOB_STATUS_CHANGED"] }),
  });
}

/** Ask Lulu to post dummy data of a topic at the subscribed URL. */
export function testLuluWebhook(webhookId: string): Promise<unknown> {
  return luluFetch(`/webhooks/${webhookId}/test-submission/PRINT_JOB_STATUS_CHANGED/`, {
    method: "POST",
    body: "{}",
  });
}

export function getLuluPrintJobStatus(
  printJobId: string | number
): Promise<LuluPrintJobStatus> {
  return luluFetch<LuluPrintJobStatus>(`/print-jobs/${printJobId}/status/`);
}

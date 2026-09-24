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

export function getLuluPrintJob(printJobId: string | number): Promise<LuluPrintJob> {
  return luluFetch<LuluPrintJob>(`/print-jobs/${printJobId}/`);
}

export function getLuluPrintJobStatus(
  printJobId: string | number
): Promise<LuluPrintJobStatus> {
  return luluFetch<LuluPrintJobStatus>(`/print-jobs/${printJobId}/status/`);
}

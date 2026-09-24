/**
 * Print fulfilment
 *
 * Every paid order becomes one Lulu print job: one line item per book, printed
 * and shipped straight to the customer. This module turns our order shape into
 * Lulu's, resolves signed URLs for the private PDFs, and leaves the raw API
 * calls to `lib/lulu.ts`.
 */

import {
  createLuluPrintJob,
  getLuluPrintJobStatus,
  type LuluLineItem,
  type LuluShippingLevel,
} from "@/lib/lulu";
import { signedFileUrl } from "@/lib/storage";

/**
 * 6" x 9", black and white, standard quality, perfect bound, 60# cream stock,
 * matte cover — what the book pipeline is built around. Books can override it
 * with their own `pod_package_id`; see book-creator/books/README.md.
 */
const DEFAULT_POD_PACKAGE_ID = "0600X0900.BW.STD.PB.060UC444.MXX";

/** Two hours of cancellation window before Lulu sends an order to production. */
const DEFAULT_PRODUCTION_DELAY_MINUTES = 120;

export type PrintableBook = {
  /** Our order row id — comes back on the matching Lulu line item */
  orderId: string;
  title: string;
  /** Stored Storage URL of the interior PDF */
  interiorUrl: string;
  /** Stored Storage URL of the print-ready wraparound cover PDF */
  coverUrl: string | null;
  podPackageId?: string | null;
};

export type PrintJobRequest = {
  /** Our reference for the whole job — the Stripe checkout session id */
  externalId: string;
  customerName: string;
  customerEmail: string;
  customerPhone?: string | null;
  shippingAddress: {
    line1: string;
    line2?: string;
    city: string;
    state: string;
    postal_code: string;
    country: string;
  };
  books: PrintableBook[];
};

export type PrintJobResponse = {
  printJobId: string;
  status: string;
  estimatedShipDate?: string;
};

function lineItemFor(book: PrintableBook, interior: string, cover: string): LuluLineItem {
  return {
    title: book.title,
    quantity: 1,
    external_id: book.orderId,
    printable_normalization: {
      pod_package_id:
        book.podPackageId || process.env.LULU_POD_PACKAGE_ID || DEFAULT_POD_PACKAGE_ID,
      interior: { source_url: interior },
      cover: { source_url: cover },
    },
  };
}

export async function createPrintJob(job: PrintJobRequest): Promise<PrintJobResponse> {
  if (job.books.length === 0) {
    throw new Error("Cannot create a print job with no books");
  }

  // Lulu requires a phone number for the carrier; it falls back to the account
  // default only if one is configured there, so fail loudly instead of guessing.
  const phone = job.customerPhone || process.env.LULU_DEFAULT_PHONE;
  if (!phone) {
    throw new Error(
      "No phone number for the shipping address — Stripe collected none and LULU_DEFAULT_PHONE is unset"
    );
  }

  const missingCovers = job.books.filter((b) => !b.coverUrl).map((b) => b.title);
  if (missingCovers.length > 0) {
    throw new Error(
      `No print-ready cover PDF on record for: ${missingCovers.join(", ")}. ` +
        "Re-run book-creator/scripts/upload_to_supabase.py for these books."
    );
  }

  const lineItems = await Promise.all(
    job.books.map(async (book) => {
      const [interior, cover] = await Promise.all([
        signedFileUrl(book.interiorUrl),
        signedFileUrl(book.coverUrl!),
      ]);
      return lineItemFor(book, interior, cover);
    })
  );

  const printJob = await createLuluPrintJob({
    contact_email:
      process.env.LULU_CONTACT_EMAIL || process.env.RESEND_FROM_EMAIL || job.customerEmail,
    external_id: job.externalId,
    line_items: lineItems,
    shipping_level:
      (process.env.LULU_SHIPPING_LEVEL as LuluShippingLevel | undefined) ?? "MAIL",
    production_delay:
      Number(process.env.LULU_PRODUCTION_DELAY_MINUTES) || DEFAULT_PRODUCTION_DELAY_MINUTES,
    shipping_address: {
      name: job.customerName,
      street1: job.shippingAddress.line1,
      street2: job.shippingAddress.line2 || undefined,
      city: job.shippingAddress.city,
      state_code: job.shippingAddress.state || undefined,
      country_code: job.shippingAddress.country || "US",
      postcode: job.shippingAddress.postal_code,
      phone_number: phone,
      email: job.customerEmail,
    },
  });

  return {
    printJobId: String(printJob.id),
    status: printJob.status?.name ?? "CREATED",
    estimatedShipDate: printJob.estimated_shipping_dates?.dispatch_min,
  };
}

export async function getPrintJobStatus(printJobId: string) {
  return getLuluPrintJobStatus(printJobId);
}

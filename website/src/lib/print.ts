/**
 * Print API integration
 *
 * This module abstracts your third-party print-on-demand provider.
 * Replace the implementation with your actual provider's SDK or REST calls.
 * Common providers: Lulu Direct, Printful, Blurb API, IngramSpark.
 */

export type PrintJobRequest = {
  orderId: string;
  bookTitle: string;
  pdfUrl: string;         // Signed URL to the print-ready PDF in Supabase Storage
  customerName: string;
  shippingAddress: {
    line1: string;
    line2?: string;
    city: string;
    state: string;
    postal_code: string;
    country: string;
  };
};

export type PrintJobResponse = {
  printJobId: string;
  estimatedShipDate: string;
  trackingUrl?: string;
};

export async function createPrintJob(
  job: PrintJobRequest
): Promise<PrintJobResponse> {
  const res = await fetch(`${process.env.PRINT_API_URL}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.PRINT_API_KEY}`,
    },
    body: JSON.stringify({
      external_id: job.orderId,
      title: job.bookTitle,
      file_url: job.pdfUrl,
      recipient: {
        name: job.customerName,
        address: job.shippingAddress,
      },
      // Adjust to match your provider's schema:
      product: { type: "paperback", paper: "60# cream", binding: "perfect" },
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Print API error ${res.status}: ${err}`);
  }

  const data = await res.json();

  // Map your provider's response shape here:
  return {
    printJobId: data.id ?? data.job_id,
    estimatedShipDate: data.estimated_ship_date ?? data.ship_date,
    trackingUrl: data.tracking_url,
  };
}

export async function getPrintJobStatus(printJobId: string) {
  const res = await fetch(`${process.env.PRINT_API_URL}/jobs/${printJobId}`, {
    headers: { Authorization: `Bearer ${process.env.PRINT_API_KEY}` },
  });
  if (!res.ok) throw new Error(`Print API status check failed: ${res.status}`);
  return res.json();
}

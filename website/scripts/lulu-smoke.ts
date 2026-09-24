/**
 * Smoke-test the Lulu print integration without placing a real order.
 *
 *   npm run lulu:test -- <book-slug>            # dry run: build and check everything
 *   npm run lulu:test -- <book-slug> --submit   # actually create the print job
 *
 * The dry run resolves the book's signed PDF URLs and fetches them the way Lulu
 * will, so a private bucket, a missing cover, or an expired key shows up here
 * rather than as a rejected print job days later. --submit is refused against
 * production unless --force is given: point LULU_API_URL at the sandbox
 * (https://api.sandbox.lulu.com) to create throwaway jobs.
 */

import { supabaseAdmin, type Book } from "@/lib/supabase";
import { signedFileUrl } from "@/lib/storage";
import { createPrintJob } from "@/lib/print";

// Lulu's own documentation example address, good enough for a sandbox job.
const TEST_SHIPPING = {
  line1: "Holstenstr. 48",
  city: "Lübeck",
  state: "",
  postal_code: "23552",
  country: "DE",
};

function redact(url: string): string {
  return url.replace(/([?&]token=)[^&]+/, "$1…");
}

async function reachable(url: string): Promise<string> {
  try {
    const res = await fetch(url, { method: "GET", headers: { Range: "bytes=0-0" } });
    return res.ok ? `OK (${res.status}, ${res.headers.get("content-type")})` : `FAILED (${res.status})`;
  } catch (err) {
    return `FAILED (${err instanceof Error ? err.message : String(err)})`;
  }
}

async function main() {
  const args = process.argv.slice(2);
  const slug = args.find((a) => !a.startsWith("--"));
  const submit = args.includes("--submit");
  const force = args.includes("--force");

  if (!slug) {
    console.error("Usage: npm run lulu:test -- <book-slug> [--submit]");
    process.exit(1);
  }

  const apiUrl = process.env.LULU_API_URL || "https://api.lulu.com";
  console.log(`Lulu API:     ${apiUrl}`);
  console.log(`Credentials:  ${process.env.LULU_CLIENT_KEY ? "LULU_CLIENT_KEY set" : "MISSING LULU_CLIENT_KEY"}`);

  const { data: book, error } = await supabaseAdmin()
    .from("books")
    .select("*")
    .eq("slug", slug)
    .single<Book>();

  if (error || !book) {
    console.error(`No book with slug "${slug}": ${error?.message ?? "not found"}`);
    process.exit(1);
  }

  console.log(`\nBook:         ${book.title}`);
  console.log(`POD package:  ${book.pod_package_id ?? `(none — falling back to ${process.env.LULU_POD_PACKAGE_ID ?? "the built-in default"})`}`);

  if (!book.cover_pdf_url) {
    console.error(
      "\nNo cover_pdf_url on this book. Re-run book-creator/scripts/upload_to_supabase.py " +
        "so the print-ready cover PDF is uploaded."
    );
    process.exit(1);
  }

  const [interior, cover] = await Promise.all([
    signedFileUrl(book.pdf_url),
    signedFileUrl(book.cover_pdf_url),
  ]);

  console.log("\nFiles Lulu will download:");
  console.log(`  interior  ${redact(interior)}\n            ${await reachable(interior)}`);
  console.log(`  cover     ${redact(cover)}\n            ${await reachable(cover)}`);

  if (!submit) {
    console.log("\nDry run — no print job created. Re-run with --submit to send it.");
    return;
  }

  if (!apiUrl.includes("sandbox") && !force) {
    console.error(
      "\nRefusing to create a real print job against production. Set LULU_API_URL to " +
        "https://api.sandbox.lulu.com, or pass --force if you really mean it."
    );
    process.exit(1);
  }

  const job = await createPrintJob({
    externalId: `smoke-test-${Date.now()}`,
    customerName: "Smoke Test",
    customerEmail: process.env.LULU_CONTACT_EMAIL || "test@example.com",
    customerPhone: process.env.LULU_DEFAULT_PHONE || "844-212-0689",
    shippingAddress: TEST_SHIPPING,
    books: [
      {
        orderId: "smoke-test",
        title: book.title,
        interiorUrl: book.pdf_url,
        coverUrl: book.cover_pdf_url,
        podPackageId: book.pod_package_id,
      },
    ],
  });

  console.log(`\nPrint job ${job.printJobId} created — status ${job.status}`);
  if (job.estimatedShipDate) console.log(`Estimated dispatch: ${job.estimatedShipDate}`);
  console.log("A created job stays UNPAID until a card on file pays it.");
}

main().catch((err) => {
  console.error("\nSmoke test failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});

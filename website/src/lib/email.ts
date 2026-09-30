import { Resend } from "resend";
import { formatPrice } from "@/lib/format";

const resend = new Resend(process.env.RESEND_API_KEY);
const FROM = process.env.RESEND_FROM_EMAIL!;

/** Where requests from the public land. */
function teamInbox(): string {
  return (
    process.env.SUBMISSIONS_NOTIFY_EMAIL ||
    process.env.LULU_CONTACT_EMAIL ||
    FROM
  );
}

/**
 * Tell the team a reader has asked for a book.
 *
 * Replies go straight to the person who asked, so answering is one keystroke
 * rather than a copy-paste out of the database.
 */
export async function sendSubmissionAlert(submission: {
  title: string;
  author: string;
  year?: string | null;
  genre?: string | null;
  reason?: string | null;
  sourceFileUrl?: string | null;
  submitterName: string;
  submitterEmail: string;
}) {
  const row = (label: string, value?: string | null) =>
    value ? `<tr><td style="padding:2px 12px 2px 0"><strong>${label}</strong></td><td>${value}</td></tr>` : "";

  await resend.emails.send({
    from: FROM,
    to: teamInbox(),
    replyTo: submission.submitterEmail,
    subject: `Book request: "${submission.title}" by ${submission.author}`,
    html: `
      <p>${submission.submitterName} has asked for a book.</p>
      <table>
        ${row("Title", submission.title)}
        ${row("Author", submission.author)}
        ${row("Year", submission.year)}
        ${row("Genre", submission.genre)}
        ${row("From", `${submission.submitterName} &lt;${submission.submitterEmail}&gt;`)}
        ${row("Source file", submission.sourceFileUrl ? `<a href="${submission.sourceFileUrl}">download</a>` : "none attached")}
      </table>
      ${submission.reason ? `<p><strong>Why they want it</strong><br/>${submission.reason}</p>` : ""}
      <p>Reply to this email to answer ${submission.submitterName} directly. The request is
      also in the <code>submissions</code> table, marked pending.</p>
    `,
  });
}

export async function sendSubmissionConfirmation(
  to: string,
  name: string,
  bookTitle: string
) {
  await resend.emails.send({
    from: FROM,
    to,
    subject: `We received your request for "${bookTitle}"`,
    html: `
      <p>Hi ${name},</p>
      <p>Thank you for submitting <strong>${bookTitle}</strong> to Out of Print Press.
      We'll research its availability and get back to you within 3–5 business days.</p>
      <p>— The Out of Print Press Team</p>
    `,
  });
}

function trackLine(orderUrl?: string): string {
  return orderUrl
    ? `<p><a href="${orderUrl}">Follow your order here</a> — we update this page as your
       book is printed and shipped, and you can cancel from it for a full refund until it
       goes to the printer.</p>`
    : "";
}

export async function sendOrderConfirmation(
  to: string,
  name: string,
  bookTitle: string,
  orderId: string,
  orderUrl?: string
) {
  await resend.emails.send({
    from: FROM,
    to,
    subject: `Your order of "${bookTitle}" is confirmed`,
    html: `
      <p>Hi ${name},</p>
      <p>Your order for <strong>${bookTitle}</strong> has been confirmed (order #${orderId}).
      We're sending it to the printer now and will email you tracking information once it ships.</p>
      ${trackLine(orderUrl)}
      <p>— The Out of Print Press Team</p>
    `,
  });
}

export async function sendSetOrderConfirmation(
  to: string,
  name: string,
  setTitle: string,
  volumeTitles: string[],
  orderId: string,
  orderUrl?: string
) {
  const volumes = volumeTitles.map((t) => `<li>${t}</li>`).join("");
  await resend.emails.send({
    from: FROM,
    to,
    subject: `Your order of the complete "${setTitle}" is confirmed`,
    html: `
      <p>Hi ${name},</p>
      <p>Your order for all ${volumeTitles.length} volumes of <strong>${setTitle}</strong>
      has been confirmed (order #${orderId}).</p>
      <ul>${volumes}</ul>
      <p>Each volume is printed individually, so they may ship separately — we'll email you
      tracking information for each as it leaves the printer.</p>
      ${trackLine(orderUrl)}
      <p>— The Out of Print Press Team</p>
    `,
  });
}

/**
 * A print job that fails leaves a paid order that nobody is printing, so tell
 * whoever runs the shop rather than only logging it.
 */
export async function sendPrintJobFailureAlert(
  orderIds: string[],
  customerEmail: string,
  reason: string
) {
  const to = process.env.LULU_CONTACT_EMAIL || FROM;
  await resend.emails.send({
    from: FROM,
    to,
    subject: `Action needed: print job failed for ${orderIds.length} paid order(s)`,
    html: `
      <p>A customer has paid, but Lulu did not accept the print job.</p>
      <p><strong>Orders:</strong> ${orderIds.join(", ")}<br/>
      <strong>Customer:</strong> ${customerEmail}</p>
      <p><strong>Lulu said:</strong></p>
      <pre style="white-space:pre-wrap">${reason}</pre>
      <p>The orders are saved with status <code>paid</code>. Fix the cause and
      resubmit the print job — the customer has not been charged twice.</p>
    `,
  });
}

export async function sendCartOrderConfirmation(
  to: string,
  name: string,
  lines: { title: string; quantity: number }[],
  orderId: string,
  orderUrl?: string
) {
  const items = lines
    .map((line) => `<li>${line.title}${line.quantity > 1 ? ` &times; ${line.quantity}` : ""}</li>`)
    .join("");
  const bookCount = lines.reduce((total, line) => total + line.quantity, 0);

  await resend.emails.send({
    from: FROM,
    to,
    subject: `Your order of ${bookCount} book${bookCount === 1 ? "" : "s"} is confirmed`,
    html: `
      <p>Hi ${name},</p>
      <p>Your order has been confirmed (order #${orderId}):</p>
      <ul>${items}</ul>
      <p>Everything is being printed to order and ships together where possible —
      we'll email you tracking information as it leaves the printer.</p>
      ${trackLine(orderUrl)}
      <p>— The Out of Print Press Team</p>
    `,
  });
}

/**
 * Sent once Lulu reports a shipment, with the carrier's own tracking links.
 * Lulu has no customer-facing order page, so the "your order" link points at
 * our own status page instead.
 */
/**
 * Sent when a customer cancels inside the window. The refund is already issued
 * by the time this goes out — unless it failed, in which case say so plainly
 * rather than promising money that is not moving.
 */
export async function sendCancellationConfirmation(
  to: string,
  name: string,
  lines: { title: string; quantity: number }[],
  refund: { refundCents: number; feeCents: number } | null,
  orderId: string,
  orderUrl?: string
) {
  const items = lines
    .map((line) => `<li>${line.title}${line.quantity > 1 ? ` &times; ${line.quantity}` : ""}</li>`)
    .join("");

  const refundLine = refund
    ? `<p>${formatPrice(refund.refundCents)} is on its way back to the card you paid with —
       what you paid, less ${formatPrice(refund.feeCents)} our card processor keeps on every
       payment, refunded or not. It usually appears on your statement within 5–10 business days.</p>`
    : `<p>We could not complete the refund automatically, so we are processing it by hand —
       you will have it within one business day. Nothing was printed and you will not be
       charged for this order.</p>`;

  await resend.emails.send({
    from: FROM,
    to,
    subject: "Your order has been cancelled",
    html: `
      <p>Hi ${name},</p>
      <p>Your order (#${orderId}) has been cancelled before it reached the printer:</p>
      <ul>${items}</ul>
      ${refundLine}
      ${trackLine(orderUrl)}
      <p>If you cancelled by mistake, just order again — nothing is lost but the wait.</p>
      <p>— The Out of Print Press Team</p>
    `,
  });
}

export async function sendShipmentNotification(
  to: string,
  name: string,
  lines: { title: string; quantity: number }[],
  trackingUrls: string[],
  carrier: string | null,
  orderUrl?: string
) {
  const items = lines
    .map((line) => `<li>${line.title}${line.quantity > 1 ? ` &times; ${line.quantity}` : ""}</li>`)
    .join("");

  const tracking = trackingUrls.length
    ? `<p>${carrier ? `${carrier} tracking` : "Tracking"}:
       ${trackingUrls.map((url) => `<a href="${url}">${url}</a>`).join("<br/>")}</p>`
    : `<p>Tracking details will appear on your order page shortly.</p>`;

  const bookCount = lines.reduce((total, line) => total + line.quantity, 0);

  await resend.emails.send({
    from: FROM,
    to,
    subject: `Your ${bookCount === 1 ? "book has" : "books have"} shipped`,
    html: `
      <p>Hi ${name},</p>
      <p>Good news — this has left the printer:</p>
      <ul>${items}</ul>
      ${tracking}
      ${trackLine(orderUrl)}
      <p>— The Out of Print Press Team</p>
    `,
  });
}

import { Resend } from "resend";

const resend = new Resend(process.env.RESEND_API_KEY);
const FROM = process.env.RESEND_FROM_EMAIL!;

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

export async function sendOrderConfirmation(
  to: string,
  name: string,
  bookTitle: string,
  orderId: string
) {
  await resend.emails.send({
    from: FROM,
    to,
    subject: `Your order of "${bookTitle}" is confirmed`,
    html: `
      <p>Hi ${name},</p>
      <p>Your order for <strong>${bookTitle}</strong> has been confirmed (order #${orderId}).
      We're sending it to the printer now and will email you tracking information once it ships.</p>
      <p>— The Out of Print Press Team</p>
    `,
  });
}

export async function sendSetOrderConfirmation(
  to: string,
  name: string,
  setTitle: string,
  volumeTitles: string[],
  orderId: string
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

export async function sendShippingNotification(
  to: string,
  name: string,
  bookTitle: string,
  trackingUrl: string
) {
  await resend.emails.send({
    from: FROM,
    to,
    subject: `"${bookTitle}" is on its way!`,
    html: `
      <p>Hi ${name},</p>
      <p>Your copy of <strong>${bookTitle}</strong> has shipped.
      <a href="${trackingUrl}">Track your package here</a>.</p>
      <p>— The Out of Print Press Team</p>
    `,
  });
}

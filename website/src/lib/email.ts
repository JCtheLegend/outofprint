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

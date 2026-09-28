import { productionDelayMinutes } from "@/lib/print";
import type { Order } from "@/lib/supabase";

/**
 * How long a customer has to change their mind.
 *
 * Lulu holds every job for `LULU_PRODUCTION_DELAY_MINUTES` before production,
 * and a job can be canceled right up until it starts printing — so the window
 * we advertise and the window the printer actually enforces are the same
 * number, and cannot drift apart.
 */
export function cancelDeadline(order: Pick<Order, "created_at">): Date {
  return new Date(new Date(order.created_at).getTime() + productionDelayMinutes() * 60_000);
}

export function isWithinCancelWindow(order: Pick<Order, "created_at">, now = new Date()): boolean {
  return now < cancelDeadline(order);
}

/** An order already shipped, delivered or canceled is past changing. */
export function isCancelable(order: Pick<Order, "created_at" | "status">, now = new Date()): boolean {
  if (["shipped", "delivered", "canceled"].includes(order.status)) return false;
  return isWithinCancelWindow(order, now);
}

export function formatDeadline(deadline: Date): string {
  return deadline.toLocaleString("en-US", {
    weekday: "long",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

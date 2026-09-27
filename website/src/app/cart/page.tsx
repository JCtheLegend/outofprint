import { CartClient } from "./CartClient";

export const metadata = { title: "Your Cart · Out of Print Press" };

export default function CartPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12">
      <div className="border-b border-border pb-8 mb-8">
        <h1 className="font-serif text-4xl font-normal mb-2">Your Cart</h1>
        <p className="text-muted text-sm">
          Each title is printed to order. Add as many books or complete sets as you like.
        </p>
      </div>
      <CartClient />
    </div>
  );
}

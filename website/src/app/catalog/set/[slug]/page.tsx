import { Suspense } from "react";
import { notFound } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { supabase } from "@/lib/supabase";
import { formatPrice } from "@/lib/format";
import {
  getSetBySlug,
  setPriceCents,
  setSavingsCents,
  volumeLabel,
  volumesSubtotalCents,
} from "@/lib/sets";
import { SetPurchasePanel, type VolumeOption } from "./SetPurchasePanel";

export async function generateStaticParams() {
  const { data } = await supabase.from("book_sets").select("slug");
  return (data ?? []).map((s) => ({ slug: s.slug }));
}

export default async function SetPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const set = await getSetBySlug(slug);
  if (!set) notFound();

  const { volumes } = set;
  const cover = set.cover_url ?? volumes.find((v) => v.cover_url)?.cover_url ?? null;
  const years = volumes.map((v) => v.year).filter((y): y is number => y != null);
  const genre = set.genre ?? volumes[0]?.genre ?? "";
  const description = set.description ?? volumes[0]?.description ?? "";

  const options: VolumeOption[] = volumes.map((v) => ({
    id: v.id,
    title: v.title,
    label: volumeLabel(v),
    priceCents: v.price_cents,
  }));

  return (
    <div className="max-w-5xl mx-auto px-6 py-12">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
        {/* Cover */}
        <div>
          <div className="relative">
            <div className="absolute inset-y-3 -right-2 left-4 bg-ink/15" aria-hidden />
            <div className="absolute inset-y-1.5 -right-1 left-2 bg-ink/25" aria-hidden />
            <div className="relative aspect-[2/3] bg-ink/10">
              {cover ? (
                <Image src={cover} alt={set.title} fill className="object-cover" />
              ) : (
                <div className="absolute inset-0 flex flex-col items-center justify-center p-8 bg-[#2d3a2e]">
                  <p className="font-serif text-xl font-semibold text-[#e8dfc0] text-center mb-2">
                    {set.title}
                  </p>
                  <p className="font-body italic text-sm text-[#a89e7a] text-center">{set.author}</p>
                </div>
              )}
            </div>
          </div>

          {/* Volumes in this set */}
          <div className="mt-8">
            <p className="section-label">In this set</p>
            <ul className="divide-y divide-border border-t border-border">
              {volumes.map((v) => (
                <li key={v.id}>
                  <Link
                    href={`/catalog/${v.id}`}
                    className="flex items-baseline justify-between gap-3 py-3 group"
                  >
                    <span className="font-body text-sm group-hover:text-rust transition-colors">
                      {volumeLabel(v) && (
                        <span className="font-semibold">{volumeLabel(v)} · </span>
                      )}
                      {v.title}
                    </span>
                    <span className="text-xs text-muted whitespace-nowrap">
                      {formatPrice(v.price_cents)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted mt-3">
              {volumes.length} volumes · {formatPrice(volumesSubtotalCents(volumes))} bought
              separately
            </p>
          </div>
        </div>

        {/* Info + purchase */}
        <div>
          <p className="section-label">{genre ? `${genre} · ` : ""}Multi-volume set</p>
          <h1 className="font-serif text-4xl font-normal mb-2 leading-tight">{set.title}</h1>
          <p className="text-muted italic text-lg mb-1">{set.author}</p>
          {years.length > 0 && (
            <p className="text-sm text-muted mb-6">
              Originally published{" "}
              {Math.min(...years) === Math.max(...years)
                ? Math.min(...years)
                : `${Math.min(...years)}–${Math.max(...years)}`}
            </p>
          )}
          {description && (
            <p className="text-sm leading-relaxed text-muted mb-8">{description}</p>
          )}

          <div className="border-t border-border pt-6">
            {/* The panel reads ?volume= to preselect a volume, which it can only
                do on the client — the Suspense boundary keeps this page
                prerenderable rather than server-rendered on every request. */}
            <Suspense fallback={<div className="h-96" />}>
              <SetPurchasePanel
                setId={set.id}
                setSlug={set.slug}
                volumes={options}
                setPriceCents={setPriceCents(set, volumes)}
                savingsCents={setSavingsCents(set, volumes)}
              />
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  );
}

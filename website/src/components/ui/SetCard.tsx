import Link from "next/link";
import Image from "next/image";
import type { BookSetWithVolumes } from "@/lib/supabase";
import { formatPrice } from "@/lib/format";
import { setPriceCents } from "@/lib/sets";

export function SetCard({ set }: { set: BookSetWithVolumes }) {
  const cover = set.cover_url ?? set.volumes.find((v) => v.cover_url)?.cover_url ?? null;
  const cheapest = Math.min(...set.volumes.map((v) => v.price_cents));

  return (
    <Link href={`/catalog/set/${set.slug}`} className="group">
      {/* Stacked spines hint that this cover stands for several volumes */}
      <div className="relative mb-3">
        <div className="absolute inset-y-2 -right-1.5 left-3 bg-ink/15" aria-hidden />
        <div className="absolute inset-y-1 -right-0.5 left-1.5 bg-ink/25" aria-hidden />
        <div
          className="relative w-full aspect-[2/3] overflow-hidden book-cover-spine"
          style={{ backgroundColor: "#2d3a2e" }}
        >
          {cover ? (
            <Image
              src={cover}
              alt={set.title}
              fill
              className="object-cover"
              sizes="(max-width: 768px) 50vw, 33vw"
            />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center p-4">
              <p className="font-serif text-sm font-semibold text-center mb-1 leading-snug text-[#e8dfc0]">
                {set.title}
              </p>
              <p className="font-body italic text-[10px] text-center text-[#a89e7a]">{set.author}</p>
            </div>
          )}
          <span className="absolute bottom-0 right-0 bg-ink/85 text-cream font-body text-[10px] tracking-widest uppercase px-2 py-1">
            {set.volumes.length} Volumes
          </span>
        </div>
      </div>
      <h3 className="font-serif text-sm font-semibold leading-snug mb-0.5 group-hover:text-rust transition-colors">
        {set.title}
      </h3>
      <p className="text-xs text-muted italic mb-1">{set.author}</p>
      <p className="text-sm font-semibold text-rust">
        From {formatPrice(cheapest)}{" "}
        <span className="font-body text-xs font-normal text-muted">
          · set {formatPrice(setPriceCents(set, set.volumes))}
        </span>
      </p>
    </Link>
  );
}

/**
 * Edition details, read defensively.
 *
 * `books.details` is copied out of each book's metadata.json, which the
 * pipeline writes by hand and not always in the same shape — one book lists
 * its contents as objects, another as sentences. Rendering an object crashes
 * the whole page, so everything is checked here and anything unexpected is
 * dropped or flattened to text, never passed through.
 */

import type { BookDetails } from "@/lib/supabase";

function text(value: unknown): string | undefined {
  if (typeof value === "string") return value.trim() || undefined;
  if (typeof value === "number") return String(value);
  return undefined;
}

/**
 * A list of strings from a string, a list of strings, or a list of
 * `{ title, subtitle?, first_publication? }` works — "Patriarcha: Or, The
 * Natural Power of Kings (1680)".
 */
function textList(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (!Array.isArray(value)) return [];

  return value.flatMap((item) => {
    const plain = text(item);
    if (plain) return [plain];
    if (item && typeof item === "object") {
      const { title, subtitle, first_publication } = item as Record<string, unknown>;
      const name = text(title);
      if (!name) return [];
      const sub = text(subtitle);
      const year = text(first_publication);
      return [`${name}${sub ? `: ${sub}` : ""}${year ? ` (${year})` : ""}`];
    }
    return [];
  });
}

export function readBookDetails(raw: unknown): BookDetails {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const d = raw as Record<string, unknown>;

  return {
    subtitle: text(d.subtitle),
    original_publication: text(d.original_publication),
    language: text(d.language),
    translator: text(d.translator),
    editor: text(d.editor),
    included_scope: textList(d.included_scope),
    trim_size: text(d.trim_size),
    contents: textList(d.contents),
    source_editions: textList(d.source_editions),
    omitted: textList(d.omitted),
  };
}

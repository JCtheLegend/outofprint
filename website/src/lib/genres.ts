/**
 * Genres
 *
 * The one list of genres a book can be filed under. It lives in genres.json so
 * the uploader (book-creator/scripts/upload_to_supabase.py) reads the same
 * list and refuses a book whose genre isn't on it — a book with no genre would
 * vanish from the catalog the moment a reader picks a filter.
 *
 * The catalog only shows the genres that actually have books; the request
 * form offers all of them, since readers ask for books we don't have yet.
 */

import genreList from "@/lib/genres.json";

export const GENRES: readonly string[] = genreList;

/** Where a book with no recognised genre is filed, so it can always be found. */
export const FALLBACK_GENRE = "Other";

export function isGenre(value: unknown): value is string {
  return typeof value === "string" && GENRES.includes(value);
}

/** A valid genre for display and filtering — never blank. */
export function displayGenre(value: string | null | undefined): string {
  return isGenre(value) ? value : FALLBACK_GENRE;
}

import { supabaseAdmin } from "@/lib/supabase";

/**
 * Supabase Storage URLs recorded on a book row point at the `book-pdfs` bucket,
 * which is private — fetching one without a token returns 400. Lulu downloads
 * the files itself, so print jobs need a signed URL instead.
 */

/** A week is far longer than Lulu needs, but survives a retried normalization. */
const DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 7;

/** Pull the bucket and object path back out of a stored Storage URL. */
export function parseStorageUrl(url: string): { bucket: string; path: string } | null {
  const match = url.match(/\/storage\/v1\/object\/(?:public\/|sign\/|authenticated\/)?([^/]+)\/(.+?)(?:\?|$)/);
  if (!match) return null;
  return { bucket: match[1], path: decodeURIComponent(match[2]) };
}

/**
 * Turn a stored Storage URL into a time-limited public one that Lulu can fetch.
 * Throws rather than returning the unusable original: a print job created with
 * an unreachable file is rejected by Lulu later, which is far harder to trace.
 */
export async function signedFileUrl(
  storageUrl: string,
  ttlSeconds: number = Number(process.env.LULU_FILE_URL_TTL_SECONDS) || DEFAULT_TTL_SECONDS
): Promise<string> {
  const parsed = parseStorageUrl(storageUrl);
  if (!parsed) {
    throw new Error(`Not a Supabase Storage URL, cannot sign it: ${storageUrl}`);
  }

  const { data, error } = await supabaseAdmin()
    .storage.from(parsed.bucket)
    .createSignedUrl(parsed.path, ttlSeconds);

  if (error || !data?.signedUrl) {
    throw new Error(
      `Failed to sign ${parsed.bucket}/${parsed.path}: ${error?.message ?? "no URL returned"}`
    );
  }
  return data.signedUrl;
}

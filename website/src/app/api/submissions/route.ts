import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin } from "@/lib/supabase";
import { sendSubmissionConfirmation } from "@/lib/email";

const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB

export async function POST(req: NextRequest) {
  try {
    const form = await req.formData();

    const title = form.get("title") as string;
    const author = form.get("author") as string;
    const year = form.get("year") as string | null;
    const genre = form.get("genre") as string | null;
    const reason = form.get("reason") as string | null;
    const submitter_name = form.get("submitter_name") as string;
    const submitter_email = form.get("submitter_email") as string;
    const file = form.get("source_file") as File | null;

    if (!title || !author || !submitter_name || !submitter_email) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    const db = supabaseAdmin();
    let source_file_url: string | null = null;

    // Upload source file to Supabase Storage if provided
    if (file && file.size > 0) {
      if (file.size > MAX_FILE_BYTES) {
        return NextResponse.json({ error: "File too large (max 50 MB)" }, { status: 400 });
      }

      const ext = file.name.split(".").pop();
      const path = `submissions/${Date.now()}-${Math.random().toString(36).slice(2)}.${ext}`;
      const bytes = await file.arrayBuffer();

      const { error: uploadError } = await db.storage
        .from("source-files")
        .upload(path, bytes, { contentType: file.type });

      if (uploadError) {
        console.error("File upload error:", uploadError);
        // Don't fail the submission just because upload failed
      } else {
        const { data: urlData } = db.storage.from("source-files").getPublicUrl(path);
        source_file_url = urlData.publicUrl;
      }
    }

    // Save submission to database
    const { error: dbError } = await db.from("submissions").insert({
      title,
      author,
      year: year || null,
      genre: genre || null,
      reason: reason || null,
      source_file_url,
      submitter_name,
      submitter_email,
      status: "pending",
    });

    if (dbError) {
      console.error("DB insert error:", dbError);
      return NextResponse.json({ error: "Failed to save submission" }, { status: 500 });
    }

    // Send confirmation email (non-blocking)
    sendSubmissionConfirmation(submitter_email, submitter_name, title).catch(
      (err) => console.error("Email error:", err)
    );

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("Submission error:", err);
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}

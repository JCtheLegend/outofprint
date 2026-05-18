"use client";

import { useState, useRef } from "react";

const GENRES = ["Fiction", "Natural History", "Philosophy", "Poetry", "History", "Science", "Other"];

type Status = "idle" | "submitting" | "success" | "error";

export function SubmissionForm() {
  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setStatus("submitting");
    setErrorMsg("");

    const form = e.currentTarget;
    const data = new FormData(form);

    try {
      const res = await fetch("/api/submissions", {
        method: "POST",
        body: data,
      });

      if (!res.ok) {
        const { error } = await res.json();
        throw new Error(error ?? "Submission failed");
      }

      setStatus("success");
      form.reset();
      setFileName("");
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  }

  if (status === "success") {
    return (
      <div className="border border-border bg-rust-light p-6">
        <h2 className="font-serif text-xl mb-2">Request received.</h2>
        <p className="text-sm text-muted leading-relaxed">
          We&apos;ll review your submission and get back to you within 3–5 business days.
          Keep an eye on your inbox.
        </p>
        <button
          onClick={() => setStatus("idle")}
          className="btn-outline mt-4 text-xs"
        >
          Submit another request
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
            Book Title <span className="text-rust">*</span>
          </label>
          <input
            name="title"
            required
            placeholder="e.g. The Lost Gardens of…"
            className="input-field"
          />
        </div>
        <div>
          <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
            Author <span className="text-rust">*</span>
          </label>
          <input
            name="author"
            required
            placeholder="Full name if known"
            className="input-field"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
            Year of Publication
          </label>
          <input
            name="year"
            placeholder="e.g. 1923"
            pattern="[0-9]{4}"
            className="input-field"
          />
        </div>
        <div>
          <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
            Genre
          </label>
          <select name="genre" className="input-field bg-white">
            <option value="">Select a genre…</option>
            {GENRES.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
          Why should this book be revived? <span className="text-rust">*</span>
        </label>
        <textarea
          name="reason"
          required
          rows={4}
          placeholder="Tell us about its significance, why it matters to you, or where you first encountered it…"
          className="input-field resize-none"
        />
      </div>

      {/* File upload */}
      <div>
        <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
          Source Material (optional)
        </label>
        <div
          className="border border-dashed border-border bg-white/50 p-6 text-center cursor-pointer hover:border-rust transition-colors"
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            name="source_file"
            accept=".pdf,.jpg,.jpeg,.png"
            className="hidden"
            onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")}
          />
          <p className="text-sm text-muted">
            {fileName ? (
              <span className="text-ink">{fileName}</span>
            ) : (
              <>
                <span className="text-ink underline">Click to upload</span> a scan or PDF
              </>
            )}
          </p>
          <p className="text-xs text-muted/70 mt-1">PDF, JPG, PNG up to 50 MB</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
            Your Name <span className="text-rust">*</span>
          </label>
          <input name="submitter_name" required placeholder="How we'll address you" className="input-field" />
        </div>
        <div>
          <label className="block text-[11px] tracking-widest uppercase text-muted mb-1.5">
            Email <span className="text-rust">*</span>
          </label>
          <input name="submitter_email" type="email" required placeholder="For our reply" className="input-field" />
        </div>
      </div>

      {status === "error" && (
        <p className="text-rust text-sm">{errorMsg}</p>
      )}

      <button
        type="submit"
        disabled={status === "submitting"}
        className="btn-primary w-full disabled:opacity-60"
      >
        {status === "submitting" ? "Submitting…" : "Submit Request"}
      </button>
    </form>
  );
}

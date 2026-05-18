import { SubmissionForm } from "./SubmissionForm";

export default function SubmitPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <div className="mb-8">
        <h1 className="font-serif text-4xl font-normal mb-2">Request a Book</h1>
        <p className="text-muted text-sm leading-relaxed">
          Know of a lost title we should revive? Tell us about it. We&apos;ll research
          its copyright status and let you know within 3–5 business days if we can bring it back.
        </p>
      </div>
      <SubmissionForm />
    </div>
  );
}

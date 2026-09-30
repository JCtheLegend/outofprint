import { SubmissionForm } from "./SubmissionForm";

// US copyright runs 95 years from publication, so the public domain line moves
// forward every January. Derive it rather than letting the page go stale.
const PUBLIC_DOMAIN_YEAR = new Date().getFullYear() - 96;

export default function SubmitPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <div className="mb-8">
        <h1 className="font-serif text-4xl font-normal mb-2">Request a Book</h1>
        <p className="text-muted text-sm leading-relaxed">
          Know of a lost title we should revive? Tell us about it. We&apos;ll research its
          copyright status and let you know within 3–5 business days if we can bring it back.
        </p>
      </div>

      <div className="border border-border p-6 mb-10 text-sm leading-relaxed">
        <p className="section-label">What we can reprint</p>
        <p className="text-muted mb-4">
          We restore books that have entered the <strong className="text-ink">public
          domain</strong> — nobody holds the rights any more, so anyone may reprint them. We
          have no way to license a book that is still in copyright, which is the one thing
          that decides whether we can say yes.
        </p>

        <p className="font-serif text-ink mb-1.5">Almost always yes</p>
        <ul className="text-muted list-disc pl-5 mb-4 space-y-1">
          <li>
            Anything published in <strong className="text-ink">{PUBLIC_DOMAIN_YEAR}</strong> or
            earlier — in the United States, copyright lasts 95 years from publication.
          </li>
          <li>Works by authors who died more than 70 years ago, published outside the US.</li>
          <li>Documents written by the US federal government, at any date.</li>
        </ul>

        <p className="font-serif text-ink mb-1.5">Sometimes</p>
        <ul className="text-muted list-disc pl-5 mb-4 space-y-1">
          <li>
            US books from {PUBLIC_DOMAIN_YEAR + 1}–1963 whose copyright was never renewed —
            a great many weren&apos;t, and we&apos;re glad to check the renewal records for you.
          </li>
          <li>
            Books whose rights holder gives permission. If you hold the rights yourself, or
            know who does, say so and we&apos;ll take it from there.
          </li>
        </ul>

        <p className="font-serif text-ink mb-1.5">We can&apos;t</p>
        <ul className="text-muted list-disc pl-5 space-y-1">
          <li>
            Reprint a book that is out of print but still in copyright — most titles from the
            1960s onward. Out of print isn&apos;t the same as out of copyright, and this is the
            commonest reason we have to decline.
          </li>
        </ul>

        <p className="text-muted mt-4">
          Unsure? Send it anyway. We&apos;d rather check than have you not ask, and a scan or
          photographs of an old edition help enormously.
        </p>
      </div>

      <SubmissionForm />
    </div>
  );
}

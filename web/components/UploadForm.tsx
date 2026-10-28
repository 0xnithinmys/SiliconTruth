"use client";

import { FileText, Loader2, Play, Upload, X } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * The thing that was missing: a way to put your own manual in.
 *
 * Three fields are genuinely required and none of them can be guessed. The
 * pages, because nobody wants a 3,000-page manual read end to end. The
 * peripheral, because one manual describes dozens. And the base address,
 * which is the one number in this whole pipeline that a HUMAN supplies —
 * asking a model for it is precisely the defect the project exists to
 * prevent, so the form asks for it plainly instead of offering to find it.
 */

export interface StartedRun {
  id: string;
  chip: string;
}

interface FieldErrors {
  [field: string]: string | undefined;
}

export default function UploadForm({
  onStarted,
  disabled,
  disabledReason,
}: {
  onStarted: (run: StartedRun) => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const [pdf, setPdf] = useState<File | null>(null);
  const [errata, setErrata] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const formRef = useRef<HTMLFormElement>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!formRef.current || busy) return;
    setBusy(true);
    setError(null);
    setFieldErrors({});

    const body = new FormData(formRef.current);
    try {
      const res = await fetch("/api/run", { method: "POST", body });
      const data = await res.json();
      if (!res.ok) {
        // The server's own sentence, not a generic failure. A 503 here is
        // actionable by a human and saying what to do beats "request failed".
        setError(data.message ?? `the server returned ${res.status}`);
        if (data.field) setFieldErrors({ [data.field]: data.message });
        return;
      }
      onStarted({ id: data.id, chip: data.chip });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const blocked = Boolean(disabled);

  return (
    <form ref={formRef} onSubmit={submit} className="space-y-5">
      <FileField
        name="pdf"
        label="Reference manual"
        hint="The PDF with the register tables."
        file={pdf}
        onFile={setPdf}
        required
        error={fieldErrors.pdf}
        disabled={blocked}
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          name="pages"
          label="Pages to read"
          placeholder="412 413"
          hint="1-indexed, space separated."
          error={fieldErrors.pages}
          disabled={blocked}
          required
        />
        <Field
          name="peripheral"
          label="Peripheral"
          placeholder="USART1"
          hint="The block being described."
          error={fieldErrors.peripheral}
          disabled={blocked}
          required
        />
        <Field
          name="base"
          label="Base address"
          placeholder="0x40011000"
          hint="You supply this; it is never read from the page."
          mono
          error={fieldErrors.base}
          disabled={blocked}
          required
        />
        <Field
          name="chip"
          label="Name this run"
          placeholder="stm32h7"
          hint="Letters, digits, dash, underscore."
          error={fieldErrors.chip}
          disabled={blocked}
          required
        />
      </div>

      <details className="group rounded-xl border border-slate-200 bg-slate-50/60">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-700 transition-colors hover:text-slate-900">
          Errata sheet
          <span className="ml-2 font-normal text-slate-500">
            optional, and the reason this tool exists
          </span>
        </summary>
        <div className="space-y-4 border-t border-slate-200 px-4 py-4">
          <p className="text-sm leading-relaxed text-slate-600">
            The register description on page 412 can be <em>wrong</em> unless
            it is cross-referenced with the workaround on page 19 of a separate
            document. Attach that document and the workarounds are injected
            into the generated driver as real code.
          </p>
          <FileField
            name="errata"
            label="Errata PDF"
            file={errata}
            onFile={setErrata}
            error={fieldErrors.errata}
            disabled={blocked}
          />
          <Field
            name="errataPage"
            label="Errata page"
            placeholder="1"
            hint="Which page of the errata to cross-reference."
            disabled={blocked}
          />
        </div>
      </details>

      <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4">
        <input
          type="checkbox"
          name="skipEmulate"
          value="true"
          disabled={blocked}
          className="mt-0.5 size-4 shrink-0 rounded border-slate-300 accent-slate-900"
        />
        <span className="text-sm leading-relaxed text-slate-600">
          <span className="font-medium text-slate-900">Skip the emulation gate.</span>{" "}
          Stop after generating the driver. Use this if Docker is not running —
          the result then says the driver was proved but never executed, rather
          than claiming it passed.
        </span>
      </label>

      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </p>
      )}

      {blocked && disabledReason && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {disabledReason}
        </p>
      )}

      <Button type="submit" size="lg" disabled={blocked || busy} className="w-full sm:w-auto">
        {busy ? <Loader2 className="animate-spin" /> : <Play />}
        {busy ? "Starting" : "Read it and build the driver"}
      </Button>
    </form>
  );
}

function Field({
  name, label, placeholder, hint, mono, error, disabled, required,
}: {
  name: string;
  label: string;
  placeholder?: string;
  hint?: string;
  mono?: boolean;
  error?: string;
  disabled?: boolean;
  required?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={name} className="block text-sm font-medium text-slate-900">
        {label}
        {required && <span className="ml-1 text-slate-400">*</span>}
      </label>
      <input
        id={name}
        name={name}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        className={[
          "w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-900",
          "placeholder:text-slate-400 disabled:bg-slate-50 disabled:text-slate-400",
          "focus:outline-none focus:ring-3",
          mono ? "font-mono" : "",
          error
            ? "border-red-300 focus:border-red-400 focus:ring-red-100"
            : "border-slate-300 focus:border-slate-400 focus:ring-slate-100",
        ].join(" ")}
      />
      {error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p className="text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  );
}

function FileField({
  name, label, hint, file, onFile, error, disabled, required,
}: {
  name: string;
  label: string;
  hint?: string;
  file: File | null;
  onFile: (f: File | null) => void;
  error?: string;
  disabled?: boolean;
  required?: boolean;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // The drop target and the <input type="file"> are the same control: the
  // input stays in the form so FormData picks it up, and the drop handler
  // writes into it rather than keeping a second copy of the file.
  function take(f: File | null) {
    onFile(f);
    if (input.current && f) {
      const dt = new DataTransfer();
      dt.items.add(f);
      input.current.files = dt.files;
    }
    if (input.current && !f) input.current.value = "";
  }

  return (
    <div className="space-y-1.5">
      <span className="block text-sm font-medium text-slate-900">
        {label}
        {required && <span className="ml-1 text-slate-400">*</span>}
      </span>
      <div
        onDragOver={(e) => {
          if (disabled) return;
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          if (disabled) return;
          e.preventDefault();
          setOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f && f.type === "application/pdf") take(f);
        }}
        className={[
          "flex items-center gap-3 rounded-xl border border-dashed px-4 py-4 transition-colors",
          disabled ? "cursor-not-allowed bg-slate-50" : "cursor-pointer",
          over
            ? "border-slate-400 bg-slate-100"
            : error
              ? "border-red-300 bg-red-50/40"
              : "border-slate-300 bg-slate-50/60 hover:bg-slate-100/70",
        ].join(" ")}
        onClick={() => !disabled && input.current?.click()}
      >
        <input
          ref={input}
          id={name}
          name={name}
          type="file"
          accept="application/pdf,.pdf"
          required={required}
          disabled={disabled}
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          className="sr-only"
        />
        {file ? (
          <>
            <FileText className="size-5 shrink-0 text-slate-500" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-slate-900">
                {file.name}
              </span>
              <span className="text-xs text-slate-500">
                {(file.size / 1e6).toFixed(1)} MB
              </span>
            </span>
            <button
              type="button"
              aria-label={`Remove ${file.name}`}
              onClick={(e) => {
                e.stopPropagation();
                take(null);
              }}
              className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700"
            >
              <X className="size-4" />
            </button>
          </>
        ) : (
          <>
            <Upload className="size-5 shrink-0 text-slate-400" />
            <span className="text-sm text-slate-600">
              Drop a PDF here, or <span className="font-medium text-slate-900">browse</span>
            </span>
          </>
        )}
      </div>
      {error ? (
        <p className="text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p className="text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  );
}

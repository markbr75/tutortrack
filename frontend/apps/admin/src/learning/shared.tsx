import { Alert, Button } from "@tutortrack/ui";
import { useId, type FormEvent, type ReactNode } from "react";

export function Table({
  caption,
  headers,
  children,
}: {
  caption: string;
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="mb-2 text-left font-semibold">{caption}</caption>
        <thead>
          <tr className="text-left">
            {headers.map((h, i) => (
              <th key={`${h}-${i}`} scope="col" className="px-2 py-1">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({ children }: { children?: ReactNode }) {
  return <td className="border-t border-border px-2 py-1 align-top">{children}</td>;
}

export function FormCard({
  title,
  submit,
  pending,
  error,
  onSubmit,
  children,
}: {
  title: string;
  submit: string;
  pending?: boolean;
  error?: Error | null;
  onSubmit: () => void;
  children: ReactNode;
}) {
  return (
    <form
      className="space-y-3 rounded-md border border-border p-4"
      aria-label={title}
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h2 className="font-semibold">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      <Button type="submit" disabled={pending}>
        {submit}
      </Button>
    </form>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1 sm:col-span-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        required={required}
        className="min-h-20 rounded-md border border-border bg-background px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

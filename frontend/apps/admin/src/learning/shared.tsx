import { useTranslation } from "@tutortrack/i18n";
import { Alert, FormPanel, RuledPanel, RuledTable, type RuledColumn } from "@tutortrack/ui";
import { useId, type ReactNode } from "react";

/**
 * A learning list: a register table in a ruled panel titled by what it lists, with skeleton
 * rows while it loads and one faded-ink sentence when it is empty.
 */
export function Table({
  caption,
  columns,
  loading,
  empty,
  aside,
  description,
  children,
}: {
  caption: string;
  columns: ReadonlyArray<RuledColumn>;
  loading?: boolean;
  /** The sentence shown instead of rows; pass it only when there are none. */
  empty?: string;
  aside?: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <RuledPanel flush title={caption} aside={aside} description={description}>
      <RuledTable
        caption={caption}
        columns={columns}
        loading={loading}
        loadingLabel={t("grid.loading")}
        empty={empty}
      >
        {children}
      </RuledTable>
    </RuledPanel>
  );
}

export function FormCard({
  title,
  submit,
  pending,
  error,
  onSubmit,
  lead,
  columns = 2,
  children,
}: {
  title: string;
  submit: string;
  pending?: boolean;
  error?: Error | null;
  onSubmit: () => void;
  lead?: ReactNode;
  columns?: 1 | 2 | 3;
  children: ReactNode;
}) {
  return (
    <FormPanel
      title={title}
      submit={submit}
      pending={pending}
      onSubmit={onSubmit}
      error={error ? <Alert tone="danger">{error.message}</Alert> : null}
      lead={lead}
      columns={columns}
    >
      {children}
    </FormPanel>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  required,
  rows,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  rows?: number;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1 sm:col-span-full">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        required={required}
        rows={rows ?? 3}
        className="rounded-md border border-field bg-surface px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-6 text-sm text-muted-foreground">{children}</p>;
}

/** A file picker whose button matches a small secondary button. */
export const fileInput =
  "max-w-full text-sm text-muted-foreground file:mr-3 file:h-8 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted";

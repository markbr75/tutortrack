import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  FactList,
  Panel,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import { fieldErrors } from "../api";
import { useEditing, type DetailField, type Value } from "./details";

/**
 * A record's details panel: ruled facts, and for people who may edit, "Edit" opens the
 * fields in place. Fields the API leaves out of the record (hidden by field permissions)
 * are not offered.
 */
export function EditableDetails({
  title,
  editLabel,
  facts,
  none,
  fields,
  record,
  canEdit,
  save,
  onSaved,
}: {
  title: string;
  /** The Edit button's accessible name ("Edit Nia Adeyemi's details"). */
  editLabel: string;
  facts: ReadonlyArray<readonly [string, ReactNode]>;
  none?: string;
  fields: DetailField[];
  record: Record<string, unknown>;
  canEdit: boolean;
  save: (changes: Record<string, Value>) => Promise<unknown>;
  onSaved: () => void;
}) {
  const edit = useEditing();
  const offered = fields.some((field) => field.name in record);
  return (
    <Panel
      title={title}
      flush
      aside={
        canEdit && offered && !edit.open ? (
          <EditButton buttonRef={edit.buttonRef} name={editLabel} onClick={edit.start} />
        ) : null
      }
    >
      {edit.open ? (
        <DetailsForm
          label={editLabel}
          fields={fields}
          record={record}
          save={save}
          onDone={(saved) => {
            if (saved) onSaved();
            edit.stop();
          }}
        />
      ) : (
        <FactList none={none} items={facts} />
      )}
    </Panel>
  );
}

/** The small secondary "Edit" button; `name` says what it edits. */
export function EditButton({
  buttonRef,
  name,
  onClick,
}: {
  buttonRef: RefObject<HTMLButtonElement>;
  name: string;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Button ref={buttonRef} size="sm" variant="secondary" aria-label={name} onClick={onClick}>
      {t("editDetails.edit")}
    </Button>
  );
}

/** The fields of a record, saved with only what changed; blanks clear numbers and dates. */
export function DetailsForm({
  label,
  fields,
  record,
  save,
  onDone,
}: {
  label: string;
  fields: DetailField[];
  record: Record<string, unknown>;
  save: (changes: Record<string, Value>) => Promise<unknown>;
  /** Called with true once saved, false on Cancel. */
  onDone: (saved: boolean) => void;
}) {
  const { t } = useTranslation();
  const shown = fields.filter((field) => field.name in record);
  const initial = Object.fromEntries(
    shown.map((field) => [field.name, toInput(field, record[field.name])]),
  );
  const [form, setForm] = useState<Record<string, string | boolean>>(initial);
  const mutation = useMutation({
    mutationFn: async () => {
      const changes = Object.fromEntries(
        shown
          .filter((field) => form[field.name] !== initial[field.name])
          .map((field) => [field.name, fromInput(field, form[field.name])]),
      );
      return Object.keys(changes).length ? save(changes) : null;
    },
    onSuccess: () => onDone(true),
  });
  const errors = fieldErrors(mutation.error);
  const unplaced = mutation.error && !shown.some((field) => errors[field.name]);
  const first = useRef<HTMLElement | null>(null);
  useEffect(() => first.current?.focus(), []);
  return (
    <form
      aria-label={label}
      className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      {shown.map((field, index) => {
        const value = form[field.name];
        const ref = index === 0 ? (node: HTMLElement | null) => (first.current = node) : undefined;
        const set = (next: string | boolean) => setForm({ ...form, [field.name]: next });
        if (field.kind === "checkbox") {
          return (
            <div key={field.name} className="sm:col-span-2">
              <CheckboxField
                ref={ref}
                label={field.label}
                hint={field.hint}
                checked={Boolean(value)}
                onChange={(e) => set(e.target.checked)}
              />
            </div>
          );
        }
        const common = { label: field.label, hint: field.hint, error: errors[field.name] };
        if (field.kind === "textarea") {
          return (
            <div key={field.name} className="sm:col-span-2">
              <TextAreaField
                ref={ref}
                {...common}
                value={String(value)}
                onChange={(e) => set(e.target.value)}
              />
            </div>
          );
        }
        return (
          <div key={field.name} className={field.wide ? "sm:col-span-2" : undefined}>
            <TextField
              ref={ref}
              {...common}
              type={field.kind ?? "text"}
              inputMode={field.kind === "number" ? "decimal" : undefined}
              autoComplete={field.autoComplete}
              value={String(value)}
              onChange={(e) => set(e.target.value)}
            />
          </div>
        );
      })}
      {unplaced ? (
        <Alert tone="danger" className="sm:col-span-2">
          {mutation.error.message}
        </Alert>
      ) : null}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" loading={mutation.isPending}>
          {t("common.save")}
        </Button>
        <Button type="button" variant="ghost" onClick={() => onDone(false)}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

function toInput(field: DetailField, value: unknown): string | boolean {
  if (field.kind === "checkbox") return Boolean(value);
  return value === null || value === undefined ? "" : String(value);
}

function fromInput(field: DetailField, value: string | boolean | undefined): Value {
  if (field.kind === "checkbox") return Boolean(value);
  const text = String(value ?? "").trim();
  if (field.kind === "number" || field.kind === "date") return text === "" ? null : text;
  return text;
}

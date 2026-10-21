import { useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, TextField } from "@tutortrack/ui";
import { useState } from "react";

import { GENDERS, splitTags, type MatchNeeds, type NeedsOverride } from "./needs";

/** The students' needs a match search used (gap G5c, FR-19-1): exam boards and SEN tags
 * (extra score factors) and, when the organisation allows it, a tutor gender preference
 * (a filter). They come from the job's students; staff can change them for this search. */
export function MatchNeedsForm({
  needs,
  onApply,
}: {
  needs: MatchNeeds;
  onApply: (override: NeedsOverride) => void;
}) {
  const { t } = useTranslation();
  const [boards, setBoards] = useState(needs.exam_boards.join(", "));
  const [tags, setTags] = useState(needs.sen_tags.join(", "));
  const [gender, setGender] = useState<NeedsOverride["gender"]>(
    (needs.gender || "") as NeedsOverride["gender"],
  );
  return (
    <form
      aria-label={t("g5c.needs.title")}
      className="flex flex-wrap items-start gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onApply({ exam_boards: splitTags(boards), sen_tags: splitTags(tags), gender });
      }}
    >
      <TextField
        label={t("g5c.needs.examBoards")}
        hint={t("g5c.needs.listHint")}
        value={boards}
        onChange={(e) => setBoards(e.target.value)}
      />
      <TextField
        label={t("g5c.needs.senTags")}
        hint={t("g5c.needs.listHint")}
        value={tags}
        onChange={(e) => setTags(e.target.value)}
      />
      {needs.gender_preference_enabled ? (
        <SelectField
          label={t("g5c.needs.gender")}
          value={gender}
          onChange={(e) => setGender(e.target.value as NeedsOverride["gender"])}
          options={[
            { value: "", label: t("g5c.needs.noPreference") },
            ...GENDERS.map((g) => ({ value: g, label: t(`g5c.genders.${g}`) })),
          ]}
        />
      ) : null}
      <Button type="submit" variant="secondary" className="sm:mt-6">
        {t("g5c.needs.apply")}
      </Button>
    </form>
  );
}

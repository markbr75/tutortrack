import { useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, TextField } from "@tutortrack/ui";
import { useState, type ReactNode } from "react";

import { GENDERS, splitTags, type MatchNeeds, type NeedsOverride } from "./needs";

/** The students' needs a match search used (gap G5c, FR-19-1): exam boards and SEN tags
 * (extra score factors) and, when the organisation allows it, a tutor gender preference
 * (a filter). They come from the job's students; staff can change them for this search.
 * Drawn as the page's one compact filter row (36px controls); `children` (another filter,
 * such as the restricted-tutors checkbox) sits before Search again. */
export function MatchNeedsForm({
  needs,
  onApply,
  children,
}: {
  needs: MatchNeeds;
  onApply: (override: NeedsOverride) => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const [boards, setBoards] = useState(needs.exam_boards.join(", "));
  const [tags, setTags] = useState(needs.sen_tags.join(", "));
  const [gender, setGender] = useState<NeedsOverride["gender"]>(
    (needs.gender || "") as NeedsOverride["gender"],
  );
  return (
    <form
      role="search"
      aria-label={t("g5c.needs.title")}
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onApply({ exam_boards: splitTags(boards), sen_tags: splitTags(tags), gender });
      }}
    >
      <div className="min-w-48 flex-1">
        <TextField
          label={t("g5c.needs.examBoards")}
          hideLabel
          size="sm"
          placeholder={`${t("g5c.needs.examBoards")} (${t("designS5.matching.commas")})`}
          title={t("g5c.needs.listHint")}
          value={boards}
          onChange={(e) => setBoards(e.target.value)}
        />
      </div>
      <div className="min-w-48 flex-1">
        <TextField
          label={t("g5c.needs.senTags")}
          hideLabel
          size="sm"
          placeholder={`${t("g5c.needs.senTags")} (${t("designS5.matching.commas")})`}
          title={t("g5c.needs.listHint")}
          value={tags}
          onChange={(e) => setTags(e.target.value)}
        />
      </div>
      {needs.gender_preference_enabled ? (
        <SelectField
          label={t("g5c.needs.gender")}
          hideLabel
          size="sm"
          value={gender}
          onChange={(e) => setGender(e.target.value as NeedsOverride["gender"])}
          options={[
            { value: "", label: t("designS5.matching.anyGender") },
            ...GENDERS.map((g) => ({ value: g, label: t(`g5c.genders.${g}`) })),
          ]}
        />
      ) : null}
      {children}
      <Button type="submit" size="sm" variant="secondary" className="h-9">
        {t("g5c.needs.apply")}
      </Button>
    </form>
  );
}

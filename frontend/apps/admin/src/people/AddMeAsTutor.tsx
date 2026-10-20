import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, useMe, usePermission } from "../api";

/** For someone who runs the business and teaches too (a sole trader, an owner who tutors):
 * one click makes them a tutor on their own login. Hidden once they are one. */
export function AddMeAsTutor() {
  const { t } = useTranslation();
  const { data: me } = useMe();
  const canCreate = usePermission("people.tutor.create");
  const queryClient = useQueryClient();
  const add = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/tutors/add-me")),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["me"] });
      void queryClient.invalidateQueries({ queryKey: ["tutors"] });
    },
  });
  if (!me?.membership || me.membership.teaches || !canCreate) return null;
  return (
    <>
      <Button variant="secondary" loading={add.isPending} onClick={() => add.mutate()}>
        {t("people.addMeAsTutor")}
      </Button>
      {add.isError ? (
        <p role="alert" className="text-sm text-danger">
          {add.error.message}
        </p>
      ) : null}
    </>
  );
}

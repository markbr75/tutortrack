import { unwrap } from "@tutortrack/api-client";
import { useMutation } from "@tanstack/react-query";

import { api } from "../api";
import { useAiFeature } from "./ai";

/** The triage request for one enquiry, shared by its button and its result. */
export function useEnquiryTriage(enquiryId: string) {
  const enabled = useAiFeature("enquiry");
  const triage = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/ai/enquiries/{enquiry_id}/triage", {
          params: { path: { enquiry_id: enquiryId } },
        }),
      ),
  });
  return { enabled, triage };
}

export type EnquiryTriage = ReturnType<typeof useEnquiryTriage>;

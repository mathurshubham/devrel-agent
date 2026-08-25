import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi, apiErrorText } from "@/hooks/use-api";

export interface OrgPersona {
    master_context?: string;
    rulesets_dos_donts?: string;
    tone_guidelines?: string;
}

export function usePersona() {
    const api = useApi();
    return useQuery({
        queryKey: ["persona"],
        queryFn: async (): Promise<OrgPersona> => {
            try {
                const { data } = await api.get("/api/org/persona");
                return data;
            } catch (err: any) {
                // Allow initial creation when no persona exists yet.
                if (err?.response?.status === 404) {
                    return { master_context: "", rulesets_dos_donts: "", tone_guidelines: "" };
                }
                throw new Error(apiErrorText(err, "Failed to fetch persona"));
            }
        },
    });
}

export function useUpdatePersona() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: OrgPersona) => {
            try {
                const { data } = await api.patch("/api/org/persona", payload);
                return data;
            } catch (err: any) {
                throw new Error(apiErrorText(err, "Failed to update persona"));
            }
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["persona"] });
        },
    });
}

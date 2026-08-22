import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export interface OrgSettings {
    reply_hook: string | null;
    scout_prompt: string | null;
    linkedin_stale_days: number | null;
    linkedin_stale_min_engagement: number | null;
    analyst_enabled: boolean;
    disclosure_reddit: boolean;
    pillar_taxonomy: string[];
    apify_monthly_budget_usd: number;
}

export type OrgSettingsPayload = Partial<OrgSettings>;

export function useOrgSettings() {
    const api = useApi();
    return useQuery({
        queryKey: ["org-settings"],
        queryFn: async (): Promise<OrgSettings> => {
            const { data } = await api.get("/api/org/settings");
            return data;
        },
    });
}

export function useUpdateOrgSettings() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: OrgSettingsPayload) => {
            const { data } = await api.patch("/api/org/settings", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["org-settings"] });
        },
    });
}

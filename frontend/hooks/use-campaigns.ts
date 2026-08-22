import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type Platform = "REDDIT" | "LINKEDIN" | "TWITTER";

export interface Campaign {
    id: number;
    platform: Platform;
    name: string;
    value: string;
    status: "ACTIVE" | "PAUSED" | "ARCHIVED";
    poll_frequency_minutes: number;
    keywords: string[];
    platform_config?: Record<string, unknown>;
    daily_draft_cap?: number;
    created_at?: string;
}

export interface RuleTestResponse {
    tested_at: string;
    subreddit: string;
    posts_tested: number;
    results: {
        post_title: string;
        post_url: string;
        matched_keywords: string[];
        confidence_score: number;
        would_trigger: boolean;
        safety_override: boolean;
        triage_reasoning: string;
    }[];
}

export function useCampaigns() {
    const api = useApi();
    return useQuery({
        queryKey: ["campaigns"],
        queryFn: async (): Promise<Campaign[]> => {
            const { data } = await api.get("/api/campaigns");
            return data;
        },
    });
}

export function useCreateCampaign() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: Partial<Campaign>) => {
            const { data } = await api.post("/api/campaigns", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

export function useUpdateCampaign() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, ...payload }: Partial<Campaign> & { id: number }) => {
            const { data } = await api.patch(`/api/campaigns/${id}`, payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

export function useToggleCampaignStatus() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, status }: { id: number; status: string }) => {
            const { data } = await api.patch(`/api/campaigns/${id}`, { status });
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

export function useDeleteCampaign() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            await api.delete(`/api/campaigns/${id}`);
            return true;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

export function useRuleTester(campaignId: number) {
    const api = useApi();
    return useMutation({
        mutationFn: async (sampleText: string): Promise<RuleTestResponse> => {
            const { data } = await api.post(`/api/campaigns/${campaignId}/test-rules`, {
                sample_text: sampleText,
            });
            return data;
        },
    });
}

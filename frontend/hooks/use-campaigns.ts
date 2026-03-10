import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface Campaign {
    id: number;
    name: string;
    status: "ACTIVE" | "PAUSED" | "ARCHIVED";
    subreddit_name: string;
    keywords: string[];
    poll_frequency_minutes: number;
    comment_fetch_limit: number;
    post_fetch_limit: number;
    include_op_context: boolean;
    max_comment_chars: number;
    is_auto_pilot_enabled: boolean;
    auto_pilot_confidence_threshold: number;
    auto_pilot_daily_limit: number;
    created_at: string;
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
    return useQuery({
        queryKey: ["campaigns"],
        queryFn: async (): Promise<Campaign[]> => {
            const res = await fetch("/api/campaigns");
            if (!res.ok) throw new Error("Failed to fetch campaigns");
            return res.json();
        },
    });
}

export function useCreateCampaign() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: Partial<Campaign>) => {
            const res = await fetch("/api/campaigns", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error("Failed to create campaign");
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

export function useToggleCampaignStatus() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, status }: { id: number; status: string }) => {
            const res = await fetch(`/api/campaigns/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status }),
            });
            if (!res.ok) throw new Error("Failed to update status");
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

export function useRuleTester(campaignId: number) {
    return useMutation({
        mutationFn: async (sampleText: string): Promise<RuleTestResponse> => {
            const res = await fetch(`/api/campaigns/${campaignId}/test-rules`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ sample_text: sampleText }),
            });
            if (!res.ok) {
                const error = await res.json();
                throw new Error(error.detail || "Failed to test rules");
            }
            return res.json();
        },
    });
}

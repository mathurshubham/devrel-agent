import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface Draft {
    id: number;
    campaign_id: number;
    status: string;
    subreddit: string;
    confidence_score: number;
    triage_reasoning: string;
    post_title: string;
    original_text: string;
    ai_draft_text: string;
    reddit_post_url: string;
    model_used: string;
    prompt_template_version: string;
    created_at: string;
    locked_by_user_id?: number;
    locked_at?: string;
}

export function useDrafts(status?: string, campaignId?: number) {
    return useQuery({
        queryKey: ["drafts", status, campaignId],
        queryFn: async (): Promise<Draft[]> => {
            let url = "/api/inbox/drafts";
            const params = new URLSearchParams();
            if (status) params.append("status", status);
            if (campaignId) params.append("campaign_id", campaignId.toString());

            if (params.toString()) {
                url += `?${params.toString()}`;
            }

            const res = await fetch(url);
            if (!res.ok) throw new Error("Failed to fetch drafts");
            return res.json();
        },
        placeholderData: (previousData) => previousData,
    });
}

export function useLockDraft() {
    return useMutation({
        mutationFn: async (id: number) => {
            const res = await fetch(`/api/inbox/drafts/${id}/lock`, { method: "POST" });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Failed to lock draft");
            }
            return res.json();
        }
    });
}

export function useApproveDraft() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const res = await fetch(`/api/inbox/drafts/${id}/approve`, { method: "POST" });
            if (!res.ok) throw new Error("Failed to approve draft");
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        }
    });
}

export function useRejectDraft() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const res = await fetch(`/api/inbox/drafts/${id}/reject`, { method: "POST" });
            if (!res.ok) throw new Error("Failed to reject draft");
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        }
    });
}

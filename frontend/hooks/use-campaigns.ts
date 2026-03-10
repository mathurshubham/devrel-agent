import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface Campaign {
    id: string;
    status: "ACTIVE" | "PAUSED";
    subreddit_name: string;
    keywords: string[];
    negative_keywords: string[];
    poll_frequency_minutes: number;
    created_at: string;
}

export interface CreateCampaignPayload {
    subreddit_name: string;
    keywords: string[];
    negative_keywords: string[];
    poll_frequency_minutes: number;
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
        mutationFn: async (payload: CreateCampaignPayload) => {
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
        mutationFn: async ({ id, status }: { id: string; status: "ACTIVE" | "PAUSED" }) => {
            const res = await fetch(`/api/campaigns/${id}/status`, {
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

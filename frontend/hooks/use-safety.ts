import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export interface SubredditSafetyProfile {
    id: number;
    org_id: number;
    subreddit: string;
    max_daily_drafts: number;
    require_manual_review: boolean;
    notes?: string;
}

export type SubredditSafetyProfileCreate = Omit<SubredditSafetyProfile, "id" | "org_id">;

export function useSafetyProfiles() {
    const api = useApi();
    return useQuery<SubredditSafetyProfile[]>({
        queryKey: ["safety-profiles"],
        queryFn: async () => {
            const { data } = await api.get("/api/safety");
            return data;
        },
    });
}

export function useCreateSafetyProfile() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: SubredditSafetyProfileCreate) => {
            const { data } = await api.post("/api/safety", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["safety-profiles"] });
        },
    });
}

export function useUpdateSafetyProfile() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, ...payload }: SubredditSafetyProfile & { id: number }) => {
            const { data } = await api.put(`/api/safety/${id}`, payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["safety-profiles"] });
        },
    });
}

export function useDeleteSafetyProfile() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const { data } = await api.delete(`/api/safety/${id}`);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["safety-profiles"] });
        },
    });
}

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";

export interface SubredditSafetyProfile {
    id: number;
    org_id: number;
    subreddit_name: string;
    allow_auto_pilot: boolean;
    max_daily_posts: number;
    require_manual_review: boolean;
    notes?: string;
}

export type SubredditSafetyProfileCreate = Omit<SubredditSafetyProfile, "id" | "org_id">;

export function useSafetyProfiles() {
    return useQuery<SubredditSafetyProfile[]>({
        queryKey: ["safety-profiles"],
        queryFn: async () => {
            const { data } = await axios.get("/api/safety/");
            return data;
        },
    });
}

export function useCreateSafetyProfile() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: SubredditSafetyProfileCreate) => {
            const { data } = await axios.post("/api/safety/", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["safety-profiles"] });
        },
    });
}

export function useUpdateSafetyProfile() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, ...payload }: SubredditSafetyProfile & { id: number }) => {
            const { data } = await axios.put(`/api/safety/${id}`, payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["safety-profiles"] });
        },
    });
}

export function useDeleteSafetyProfile() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const { data } = await axios.delete(`/api/safety/${id}`);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["safety-profiles"] });
        },
    });
}

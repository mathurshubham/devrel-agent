import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type Platform = "REDDIT" | "LINKEDIN" | "TWITTER";
export type PromptType = "MASTER_CONTEXT" | "ANGLE" | "SCOUT" | "ANALYST";

export interface PromptTemplate {
    id: number;
    org_id: number | null; // null = system default
    platform: Platform;
    type: PromptType;
    name: string;
    content: string;
    version: number;
}

export interface CreatePromptPayload {
    platform: Platform;
    type: PromptType;
    name: string;
    content: string;
}

export function usePrompts() {
    const api = useApi();
    return useQuery({
        queryKey: ["prompts"],
        queryFn: async (): Promise<PromptTemplate[]> => {
            const { data } = await api.get("/api/prompts");
            return data;
        },
    });
}

export function useCreatePrompt() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: CreatePromptPayload) => {
            const { data } = await api.post("/api/prompts", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["prompts"] });
        },
    });
}

export function useUpdatePrompt() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, content }: { id: number; content: string }) => {
            const { data } = await api.patch(`/api/prompts/${id}`, { content });
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["prompts"] });
        },
    });
}

export function useDeletePrompt() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            await api.delete(`/api/prompts/${id}`);
            return true;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["prompts"] });
        },
    });
}

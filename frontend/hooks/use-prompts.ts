import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface PromptTemplate {
    id: number;
    title: string;
    description: string;
    category: string;
    prompt_body: string;
    version: number;
    is_system_default: boolean;
    org_id?: number;
}

export function usePrompts() {
    return useQuery({
        queryKey: ["prompts"],
        queryFn: async (): Promise<PromptTemplate[]> => {
            const res = await fetch("/api/prompts");
            if (!res.ok) throw new Error("Failed to fetch prompts");
            return res.json();
        },
    });
}

export function useCreatePrompt() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: Partial<PromptTemplate>) => {
            const res = await fetch("/api/prompts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error("Failed to create prompt");
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["prompts"] });
        },
    });
}

export function useUpdatePrompt() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, ...payload }: Partial<PromptTemplate> & { id: number }) => {
            const res = await fetch(`/api/prompts/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Failed to update prompt");
            }
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["prompts"] });
        },
    });
}

export function useDeletePrompt() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const res = await fetch(`/api/prompts/${id}`, {
                method: "DELETE",
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Failed to delete prompt");
            }
            return true;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["prompts"] });
        },
    });
}

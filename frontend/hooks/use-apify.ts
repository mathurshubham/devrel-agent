import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export interface ApifyToken {
    id: number;
    label: string;
    masked_token: string;
    plan_cap_usd: number;
    is_active: boolean;
}

export interface ApifyCredit {
    token_id: number | null;
    label: string | null;
    used_usd: number;
    max_usd: number;
    remaining_usd: number;
    pct_used: number;
    usage_cycle_start: string | null;
    usage_cycle_end: string | null;
    is_usable: boolean;
    error?: string | null;
}

export interface ApifyCreditsResponse {
    tokens: ApifyCredit[];
    total_remaining_usd: number;
}

export interface AddApifyTokenPayload {
    label: string;
    token: string;
}

export function useApifyTokens() {
    const api = useApi();
    return useQuery({
        queryKey: ["apify-tokens"],
        queryFn: async (): Promise<ApifyToken[]> => {
            const { data } = await api.get("/api/org/apify/tokens");
            return data;
        },
    });
}

export function useApifyCredits() {
    const api = useApi();
    return useQuery({
        queryKey: ["apify-credits"],
        queryFn: async (): Promise<ApifyCreditsResponse> => {
            const { data } = await api.get("/api/org/apify/credits");
            return data;
        },
        refetchInterval: 60_000,
    });
}

export function useAddApifyToken() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: AddApifyTokenPayload) => {
            const { data } = await api.post("/api/org/apify/tokens", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["apify-tokens"] });
            queryClient.invalidateQueries({ queryKey: ["apify-credits"] });
        },
    });
}

export function useUpdateApifyToken() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, ...payload }: { id: number; label?: string; plan_cap_usd?: number; is_active?: boolean }) => {
            const { data } = await api.patch(`/api/org/apify/tokens/${id}`, payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["apify-tokens"] });
            queryClient.invalidateQueries({ queryKey: ["apify-credits"] });
        },
    });
}

export function useDeleteApifyToken() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            await api.delete(`/api/org/apify/tokens/${id}`);
            return true;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["apify-tokens"] });
            queryClient.invalidateQueries({ queryKey: ["apify-credits"] });
        },
    });
}

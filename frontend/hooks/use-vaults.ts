import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface VaultStatus {
    openai_connected: boolean;
    anthropic_connected: boolean;
    gemini_connected: boolean;
    openrouter_connected: boolean;
    reddit_username: string | null;
    current_model?: string;
    current_provider?: string;
}

export interface LLMConfigPayload {
    provider: "openai" | "anthropic" | "gemini" | "openrouter";
    model_name?: string;
    api_key?: string;
    max_daily_llm_tokens?: number;
    max_monthly_llm_cost_usd?: number;
}

export interface SaveRedditCredsPayload {
    client_id: string;
    client_secret: string;
    username: string;
    password: string;
}

export function useVaultStatus() {
    return useQuery({
        queryKey: ["vault_status"],
        queryFn: async (): Promise<VaultStatus> => {
            // Updated to point to the actual backend logic
            const res = await fetch("/api/org/status");
            // Note: I might need to implement this endpoint in the backend if not present!
            // Let's check org.py later if I missed a GET status endpoint.
            if (!res.ok) throw new Error("Failed to fetch vault status");
            return res.json();
        },
    });
}

export function useUpdateLLMConfig() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: LLMConfigPayload) => {
            const res = await fetch("/api/org/llm-config", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Failed to update LLM config");
            }
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["vault_status"] });
        },
    });
}

export function useSaveRedditCreds() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: SaveRedditCredsPayload) => {
            const res = await fetch("/api/org/reddit", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Failed to save Reddit credentials");
            }
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["vault_status"] });
        },
    });
}

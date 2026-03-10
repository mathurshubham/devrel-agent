import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface VaultStatus {
    openai_connected: boolean;
    anthropic_connected: boolean;
    reddit_username: string | null;
}

export interface SaveLLMKeyPayload {
    provider: "openai" | "anthropic";
    api_key: string;
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
            const res = await fetch("/api/vault/status");
            if (!res.ok) throw new Error("Failed to fetch vault status");
            return res.json();
        },
    });
}

export function useSaveLLMKey() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: SaveLLMKeyPayload) => {
            const res = await fetch("/api/vault/llm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Failed to save LLM key");
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
            const res = await fetch("/api/vault/reddit", {
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

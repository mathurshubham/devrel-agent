import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type LLMProvider = "openrouter" | "openai" | "anthropic" | "gemini" | "ollama" | "custom";

export interface OrgStatus {
    current_provider?: LLMProvider | null;
    current_model?: string | null;
    custom_base_url?: string | null;
    max_daily_llm_tokens?: number | null;
    max_monthly_llm_cost_usd?: number | null;
    kill_switch_active?: boolean;
    [key: string]: unknown;
}

export interface LLMConfigPayload {
    provider: LLMProvider;
    model_name?: string;
    api_key?: string;
    custom_base_url?: string;
    max_daily_llm_tokens?: number;
    max_monthly_llm_cost_usd?: number;
}

export function useVaultStatus() {
    const api = useApi();
    return useQuery({
        queryKey: ["org_status"],
        queryFn: async (): Promise<OrgStatus> => {
            const { data } = await api.get("/api/org/status");
            return data;
        },
    });
}

export function useUpdateLLMConfig() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: LLMConfigPayload) => {
            const { data } = await api.patch("/api/org/llm-config", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["org_status"] });
        },
    });
}

export interface OrgUsage {
    daily_tokens: number;
    monthly_cost_usd: number;
    max_daily_tokens?: number | null;
    max_monthly_cost?: number | null;
}

export function useOrgUsage() {
    const api = useApi();
    return useQuery({
        queryKey: ["org_usage"],
        queryFn: async (): Promise<OrgUsage> => {
            const { data } = await api.get("/api/org/usage");
            return data;
        },
    });
}

export interface AuditLogEntry {
    id: number;
    action: string;
    details?: Record<string, unknown>;
    user_id?: number | null;
    timestamp: string;
}

export function useAuditLogs() {
    const api = useApi();
    return useQuery({
        queryKey: ["audit_logs"],
        queryFn: async (): Promise<AuditLogEntry[]> => {
            const { data } = await api.get("/api/org/audit-logs");
            return data;
        },
    });
}

export function useKillSwitch() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async () => {
            const { data } = await api.post("/api/org/kill-switch");
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["org_status"] });
            queryClient.invalidateQueries({ queryKey: ["campaigns"] });
        },
    });
}

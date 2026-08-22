import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type Platform = "REDDIT" | "LINKEDIN" | "TWITTER";

export type DraftStatus =
    | "PENDING"
    | "AWAITING_CONFIRM"
    | "POSTED"
    | "REJECTED"
    | "IGNORED"
    | "FAILED"
    | "FAILED_COST_LIMIT";

export type SignalTier = "HIGH" | "MEDIUM" | "LOW" | null;

export interface Draft {
    id: number;
    platform: Platform;
    post_id: string;
    author_name?: string | null;
    author_headline?: string | null;
    author_profile_url?: string | null;
    title: string;
    original_content: string;
    top_comments?: string[] | null;
    url?: string | null;
    reply_target_url?: string | null;
    reply_type?: "NEW_COMMENT" | "REPLY_TO_COMMENT" | null;
    angle_name?: string | null;
    ai_draft_text: string;
    status: DraftStatus;
    confidence: number;
    triage_reasoning?: string | null;
    signal_tier?: SignalTier;
    reactions?: number | null;
    comments_count?: number | null;
    shares?: number | null;
    engagement_score?: number | null;
    posted_at_source?: string | null;
    live_url?: string | null;
    reject_reason?: string | null;
    campaign_id?: number | null;
    created_at: string;
}

export interface DraftListResponse {
    items: Draft[];
    total: number;
}

export interface DraftListParams {
    status?: DraftStatus;
    campaign_id?: number;
    platform?: Platform;
    q?: string;
    page?: number;
}

export interface OpenCopyResponse {
    clipboard_text: string;
    reply_target_url: string;
}

export function useDrafts(params: DraftListParams = {}) {
    const api = useApi();
    const { status, campaign_id, platform, q, page } = params;
    return useQuery({
        queryKey: ["drafts", status, campaign_id, platform, q, page],
        queryFn: async (): Promise<DraftListResponse> => {
            const { data } = await api.get("/api/inbox/drafts", {
                params: { status, campaign_id, platform, q, page },
            });
            return data;
        },
        placeholderData: (previousData) => previousData,
    });
}

export function useLockDraft() {
    const api = useApi();
    return useMutation({
        mutationFn: async (id: number) => {
            const { data } = await api.post(`/api/inbox/drafts/${id}/lock`);
            return data;
        },
    });
}

export function useUpdateDraft() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, ai_draft_text }: { id: number; ai_draft_text: string }) => {
            const { data } = await api.patch(`/api/inbox/drafts/${id}`, { ai_draft_text });
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        },
    });
}

export function useOpenCopyDraft() {
    const api = useApi();
    return useMutation({
        mutationFn: async (id: number): Promise<OpenCopyResponse> => {
            const { data } = await api.post(`/api/inbox/drafts/${id}/open-copy`);
            return data;
        },
    });
}

export function useConfirmPosted() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, live_url }: { id: number; live_url?: string }) => {
            const { data } = await api.post(`/api/inbox/drafts/${id}/confirm-posted`, { live_url });
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        },
    });
}

export function useUnconfirmDraft() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const { data } = await api.post(`/api/inbox/drafts/${id}/unconfirm`);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        },
    });
}

export function useRejectDraft() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, reason }: { id: number; reason: string }) => {
            const { data } = await api.post(`/api/inbox/drafts/${id}/reject`, { reason });
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        },
    });
}

export function useIgnoreDraft() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            const { data } = await api.post(`/api/inbox/drafts/${id}/ignore`);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        },
    });
}

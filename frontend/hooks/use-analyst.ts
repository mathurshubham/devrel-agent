import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type AnalystRunStatus = "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";

export interface AnalystStatus {
    status: AnalystRunStatus;
    week_of: string | null;
    started_at: string | null;
    finished_at: string | null;
}

export interface AnalystRunResponse {
    run_id: number;
}

export interface IntelBriefSummary {
    id: number;
    week_of: string;
    created_at: string;
}

export interface IntelBrief {
    id: number;
    week_of: string;
    content_md: string;
}

export interface ForecastWeek {
    week_of: string;
    count: number;
}

export interface PillarForecast {
    pillar: string;
    weeks: ForecastWeek[];
    momentum: number;
}

export type WatchlistTier = 1 | 2;

export interface TargetAuthor {
    id: number;
    name: string;
    tier: WatchlistTier;
    profile_url: string;
}

export type TargetAuthorPayload = Omit<TargetAuthor, "id">;

export type CompetitorPlatform = "REDDIT" | "LINKEDIN" | "TWITTER";

export interface Competitor {
    id: number;
    platform: CompetitorPlatform;
    name: string;
    url: string;
}

export type CompetitorPayload = Omit<Competitor, "id">;

export function useAnalystStatus() {
    const api = useApi();
    return useQuery({
        queryKey: ["analyst-status"],
        queryFn: async (): Promise<AnalystStatus> => {
            const { data } = await api.get("/api/analyst/status");
            return data;
        },
        refetchInterval: (query) => (query.state.data?.status === "RUNNING" ? 5_000 : 30_000),
    });
}

export function useRunAnalyst() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (): Promise<AnalystRunResponse> => {
            const { data } = await api.post("/api/analyst/run");
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["analyst-status"] });
        },
    });
}

export function useIntelBriefs() {
    const api = useApi();
    return useQuery({
        queryKey: ["intel-briefs"],
        queryFn: async (): Promise<IntelBriefSummary[]> => {
            const { data } = await api.get("/api/analyst/briefs");
            return data;
        },
    });
}

export function useLatestIntelBrief() {
    const api = useApi();
    return useQuery({
        queryKey: ["intel-brief", "latest"],
        queryFn: async (): Promise<IntelBrief | null> => {
            try {
                const { data } = await api.get("/api/analyst/briefs/latest");
                return data;
            } catch (err: any) {
                if (err?.response?.status === 404) return null;
                throw err;
            }
        },
    });
}

export function useIntelBrief(id: number | null) {
    const api = useApi();
    return useQuery({
        queryKey: ["intel-brief", id],
        queryFn: async (): Promise<IntelBrief> => {
            const { data } = await api.get(`/api/analyst/briefs/${id}`);
            return data;
        },
        enabled: id !== null,
    });
}

export function usePillarForecast() {
    const api = useApi();
    return useQuery({
        queryKey: ["analyst-forecast"],
        queryFn: async (): Promise<PillarForecast[]> => {
            const { data } = await api.get("/api/analyst/forecast");
            return data;
        },
    });
}

export function useTargetAuthors() {
    const api = useApi();
    return useQuery({
        queryKey: ["analyst-authors"],
        queryFn: async (): Promise<TargetAuthor[]> => {
            const { data } = await api.get("/api/analyst/authors");
            return data;
        },
    });
}

export function useAddTargetAuthor() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: TargetAuthorPayload) => {
            const { data } = await api.post("/api/analyst/authors", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["analyst-authors"] });
        },
    });
}

export function useDeleteTargetAuthor() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            await api.delete(`/api/analyst/authors/${id}`);
            return true;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["analyst-authors"] });
        },
    });
}

export function useCompetitors() {
    const api = useApi();
    return useQuery({
        queryKey: ["analyst-competitors"],
        queryFn: async (): Promise<Competitor[]> => {
            const { data } = await api.get("/api/analyst/competitors");
            return data;
        },
    });
}

export function useAddCompetitor() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: CompetitorPayload) => {
            const { data } = await api.post("/api/analyst/competitors", payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["analyst-competitors"] });
        },
    });
}

export function useDeleteCompetitor() {
    const api = useApi();
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id: number) => {
            await api.delete(`/api/analyst/competitors/${id}`);
            return true;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["analyst-competitors"] });
        },
    });
}

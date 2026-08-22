import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type Platform = "REDDIT" | "LINKEDIN" | "TWITTER";

export interface AngleStat {
    platform: Platform;
    angle_name: string;
    drafted: number;
    posted: number;
    acceptance_rate: number;
    avg_engagement: number;
}

export interface PlatformStat {
    platform: Platform;
    drafted: number;
    posted: number;
    acceptance_rate: number;
}

export interface AnalyticsTotals {
    drafted: number;
    posted: number;
    rejected: number;
    reject_reasons: Record<string, number>;
}

export interface AnalyticsSpend {
    llm_month_usd: number;
    llm_cap_usd: number | null;
    apify_month_usd: number;
    apify_budget_usd: number;
}

export interface AnalyticsSummary {
    angles: AngleStat[];
    platforms: PlatformStat[];
    totals: AnalyticsTotals;
    spend: AnalyticsSpend;
}

export function useAnalyticsSummary() {
    const api = useApi();
    return useQuery({
        queryKey: ["analytics-summary"],
        queryFn: async (): Promise<AnalyticsSummary> => {
            const { data } = await api.get("/api/analytics/summary");
            return data;
        },
    });
}

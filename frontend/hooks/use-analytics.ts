import { useQuery } from "@tanstack/react-query";
import { useApi } from "@/hooks/use-api";

export type Platform = "REDDIT" | "LINKEDIN" | "TWITTER";

export interface AngleLeaderboardRow {
    platform: Platform;
    angle: string;
    drafted: number;
    posted: number;
    acceptance_rate: number;
    avg_engagement: number;
}

export interface PlatformPerformanceRow {
    platform: Platform;
    drafted: number;
    posted: number;
    rejected: number;
    acceptance_rate: number;
    avg_engagement: number;
}

export interface AnalyticsTotals {
    drafted: number;
    posted: number;
    rejected: number;
    reject_reasons: Record<string, number>;
}

export interface LlmSpend {
    daily_tokens: number;
    monthly_cost_usd: number;
    max_daily_tokens: number | null;
    max_monthly_cost_usd: number | null;
}

export interface ApifySpend {
    month: string;
    spent_usd: number;
    budget_usd: number;
    utilization_pct: number;
}

export interface AnalyticsSpend {
    llm: LlmSpend;
    apify: ApifySpend;
}

export interface AnalyticsSummary {
    totals: AnalyticsTotals;
    angle_leaderboard: AngleLeaderboardRow[];
    platform_performance: PlatformPerformanceRow[];
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

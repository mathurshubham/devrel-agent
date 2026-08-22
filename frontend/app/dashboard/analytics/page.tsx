"use client";

import * as React from "react";
import { BarChart3, Loader2, ThumbsDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { AngleLeaderboard } from "@/components/analytics/angle-leaderboard";
import { SpendMeter } from "@/components/analytics/spend-meter";
import { useAnalyticsSummary } from "@/hooks/use-analytics";
import type { Platform } from "@/hooks/use-analytics";

const PLATFORM_STYLES: Record<Platform, string> = {
    REDDIT: "bg-orange-500/10 text-orange-500 border-orange-500/20",
    LINKEDIN: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    TWITTER: "bg-sky-500/10 text-sky-500 border-sky-500/20",
};

const REJECT_REASON_LABELS: Record<string, string> = {
    "off-tone": "Off tone",
    "wrong thread": "Wrong thread",
    factual: "Factual issue",
    other: "Other",
};

export default function AnalyticsPage() {
    const { data, isLoading } = useAnalyticsSummary();
    const [platformFilter, setPlatformFilter] = React.useState<Platform | "ALL">("ALL");

    if (isLoading) {
        return (
            <div className="flex h-[calc(100vh-200px)] items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    const totals = data?.totals;
    const spend = data?.spend;
    const platforms = data?.platforms || [];
    const angles = data?.angles || [];

    const overallAcceptance = totals && totals.drafted > 0 ? (totals.posted / totals.drafted) * 100 : 0;
    const rejectReasons = totals ? Object.entries(totals.reject_reasons) : [];
    const maxRejectCount = Math.max(1, ...rejectReasons.map(([, n]) => n));

    return (
        <div className="flex flex-col gap-8 p-8 max-w-7xl mx-auto">
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 text-foreground">
                    <BarChart3 className="h-5 w-5 text-primary" />
                    <h1 className="text-xl font-semibold tracking-tight">Analytics</h1>
                </div>
                <p className="text-sm text-muted-foreground">
                    Angle performance, acceptance rates, and spend against your org's caps.
                </p>
            </div>

            {/* Totals + spend */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="flex flex-col gap-1 rounded-md border border-border/40 bg-muted/5 p-4">
                    <span className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Drafted</span>
                    <span className="text-2xl font-semibold tabular-nums">{totals?.drafted ?? 0}</span>
                </div>
                <div className="flex flex-col gap-1 rounded-md border border-border/40 bg-muted/5 p-4">
                    <span className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Posted</span>
                    <span className="text-2xl font-semibold tabular-nums">{totals?.posted ?? 0}</span>
                </div>
                <div className="flex flex-col gap-1 rounded-md border border-border/40 bg-muted/5 p-4">
                    <span className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Rejected</span>
                    <span className="text-2xl font-semibold tabular-nums">{totals?.rejected ?? 0}</span>
                </div>
                <div className="flex flex-col gap-1 rounded-md border border-border/40 bg-muted/5 p-4">
                    <span className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Acceptance</span>
                    <span className="text-2xl font-semibold tabular-nums text-primary">{overallAcceptance.toFixed(0)}%</span>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="flex flex-col gap-3">
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                        <ThumbsDown className="h-3.5 w-3.5" />
                        Reject reasons
                    </h2>
                    {rejectReasons.length === 0 ? (
                        <div className="flex items-center justify-center py-10 border border-dashed border-border/60 rounded-md bg-muted/5">
                            <p className="text-xs text-muted-foreground">No rejections recorded yet.</p>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2 border border-border/40 rounded-md bg-muted/5 p-4">
                            {rejectReasons.map(([reason, count]) => (
                                <div key={reason} className="flex items-center gap-3">
                                    <span className="text-xs w-28 shrink-0 truncate">{REJECT_REASON_LABELS[reason] || reason}</span>
                                    <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                                        <div
                                            className="h-full bg-primary/70"
                                            style={{ width: `${(count / maxRejectCount) * 100}%` }}
                                        />
                                    </div>
                                    <span className="text-xs font-mono text-muted-foreground w-8 text-right">{count}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <div className="flex flex-col gap-3">
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Spend vs. caps</h2>
                    <div className="flex flex-col gap-3">
                        <SpendMeter label="LLM spend (this month)" usedUsd={spend?.llm_month_usd ?? 0} capUsd={spend?.llm_cap_usd ?? null} />
                        <SpendMeter label="Apify spend (this month)" usedUsd={spend?.apify_month_usd ?? 0} capUsd={spend?.apify_budget_usd ?? null} />
                    </div>
                </div>
            </div>

            {/* Platform performance cards */}
            <div className="flex flex-col gap-3">
                <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Platform performance</h2>
                {platforms.length === 0 ? (
                    <div className="flex items-center justify-center py-10 border border-dashed border-border/60 rounded-md bg-muted/5">
                        <p className="text-xs text-muted-foreground">No platform activity yet.</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {platforms.map((p) => (
                            <div key={p.platform} className="flex flex-col gap-3 rounded-md border border-border/40 bg-muted/5 p-4">
                                <Badge variant="outline" className={`w-fit text-[10px] font-bold py-0 h-5 ${PLATFORM_STYLES[p.platform] || ""}`}>
                                    {p.platform}
                                </Badge>
                                <div className="grid grid-cols-3 gap-2">
                                    <div className="flex flex-col">
                                        <span className="text-[9px] uppercase font-mono text-muted-foreground">Drafted</span>
                                        <span className="text-lg font-semibold tabular-nums">{p.drafted}</span>
                                    </div>
                                    <div className="flex flex-col">
                                        <span className="text-[9px] uppercase font-mono text-muted-foreground">Posted</span>
                                        <span className="text-lg font-semibold tabular-nums">{p.posted}</span>
                                    </div>
                                    <div className="flex flex-col">
                                        <span className="text-[9px] uppercase font-mono text-muted-foreground">Accept.</span>
                                        <span className="text-lg font-semibold tabular-nums text-primary">{(p.acceptance_rate * 100).toFixed(0)}%</span>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Angle leaderboard */}
            <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Angle leaderboard</h2>
                    <div className="flex items-center gap-1.5">
                        {(["ALL", "REDDIT", "LINKEDIN", "TWITTER"] as const).map((p) => (
                            <button
                                key={p}
                                onClick={() => setPlatformFilter(p)}
                                className={`h-7 px-3 rounded-md text-[10px] font-bold uppercase tracking-wide transition-colors ${
                                    platformFilter === p
                                        ? "bg-primary/10 text-primary border border-primary/30"
                                        : "text-muted-foreground border border-transparent hover:bg-muted/40"
                                }`}
                            >
                                {p}
                            </button>
                        ))}
                    </div>
                </div>
                <AngleLeaderboard angles={angles} platformFilter={platformFilter} />
            </div>
        </div>
    );
}

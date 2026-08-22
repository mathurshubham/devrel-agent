"use client";

import { TrendingUp, TrendingDown, Minus, Sparkles } from "lucide-react";
import type { PillarForecast, PillarMomentumRow } from "@/hooks/use-analyst";

function DeltaBadge({ delta }: { delta?: number }) {
    if (delta === undefined || delta === 0) {
        return (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-muted-foreground">
                <Minus className="h-3 w-3" />0
            </span>
        );
    }
    if (delta > 0) {
        return (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-green-500">
                <TrendingUp className="h-3 w-3" />+{delta}
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1 text-[10px] font-mono text-red-500">
            <TrendingDown className="h-3 w-3" />{delta}
        </span>
    );
}

function PillarRow({ row }: { row: PillarMomentumRow }) {
    const latest = row.series.length > 0 ? row.series[row.series.length - 1] : 0;
    return (
        <div className="flex items-center justify-between rounded-md border border-border/40 bg-background p-3">
            <div className="flex flex-col gap-0.5 min-w-0">
                <span className="text-sm font-medium truncate">{row.pillar}</span>
                <span className="text-[10px] text-muted-foreground font-mono">
                    {row.series.join(" → ")} (latest: {latest})
                </span>
            </div>
            <DeltaBadge delta={row.delta} />
        </div>
    );
}

function PillarSection({
    title,
    rows,
    emptyLabel,
}: {
    title: string;
    rows: PillarMomentumRow[];
    emptyLabel: string;
}) {
    return (
        <div className="flex flex-col gap-2">
            <h3 className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">{title}</h3>
            {rows.length === 0 ? (
                <p className="text-xs text-muted-foreground italic px-1 py-1">{emptyLabel}</p>
            ) : (
                <div className="flex flex-col gap-2">
                    {rows.map((row) => (
                        <PillarRow key={row.pillar} row={row} />
                    ))}
                </div>
            )}
        </div>
    );
}

export function PillarForecastChart({ data }: { data: PillarForecast | null }) {
    if (!data || (data.trending.length === 0 && data.declining.length === 0 && data.stable.length === 0)) {
        return (
            <div className="flex flex-col items-center justify-center py-16 border border-dashed border-border/60 rounded-md bg-muted/5">
                <p className="text-sm text-muted-foreground">No forecast data yet — run the Analyst at least once.</p>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-5">
            {data.recommended_focus.length > 0 && (
                <div className="flex items-start gap-3 rounded-md border border-primary/30 bg-primary/5 p-4">
                    <Sparkles className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                    <div className="flex flex-col gap-1">
                        <span className="text-sm font-medium text-primary">Recommended focus</span>
                        <p className="text-xs text-muted-foreground">
                            {data.recommended_focus.join(", ")}
                        </p>
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <PillarSection title="Trending" rows={data.trending} emptyLabel="No trending pillars this week." />
                <PillarSection title="Declining" rows={data.declining} emptyLabel="No declining pillars this week." />
                <PillarSection title="Stable" rows={data.stable} emptyLabel="No stable pillars this week." />
            </div>

            {data.weeks_analyzed.length > 0 && (
                <p className="text-[10px] text-muted-foreground font-mono">
                    Based on {data.weeks_analyzed.length} week{data.weeks_analyzed.length === 1 ? "" : "s"} of data (
                    {data.weeks_analyzed.map((w) => new Date(w).toLocaleDateString(undefined, { month: "short", day: "numeric" })).join(", ")}
                    )
                </p>
            )}
        </div>
    );
}

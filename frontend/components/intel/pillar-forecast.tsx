"use client";

import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { PillarForecast } from "@/hooks/use-analyst";

function MomentumBadge({ momentum }: { momentum: number }) {
    if (momentum > 0) {
        return (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-green-500">
                <TrendingUp className="h-3 w-3" />+{momentum.toFixed(0)}%
            </span>
        );
    }
    if (momentum < 0) {
        return (
            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-red-500">
                <TrendingDown className="h-3 w-3" />{momentum.toFixed(0)}%
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1 text-[10px] font-mono text-muted-foreground">
            <Minus className="h-3 w-3" />0%
        </span>
    );
}

export function PillarForecastChart({ data }: { data: PillarForecast[] }) {
    if (data.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-16 border border-dashed border-border/60 rounded-md bg-muted/5">
                <p className="text-sm text-muted-foreground">No forecast data yet — run the Analyst at least once.</p>
            </div>
        );
    }

    const maxCount = Math.max(1, ...data.flatMap((p) => p.weeks.map((w) => w.count)));

    return (
        <div className="flex flex-col gap-5">
            {data.map((pillar) => (
                <div key={pillar.pillar} className="flex flex-col gap-2 border border-border/40 rounded-md p-4 bg-muted/5">
                    <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">{pillar.pillar}</span>
                        <MomentumBadge momentum={pillar.momentum} />
                    </div>
                    <div className="flex items-end gap-3 h-20">
                        {pillar.weeks.map((week) => {
                            const heightPct = Math.max(4, (week.count / maxCount) * 100);
                            return (
                                <div key={week.week_of} className="flex flex-1 flex-col items-center gap-1 h-full justify-end">
                                    <span className="text-[10px] font-mono text-muted-foreground">{week.count}</span>
                                    <div
                                        className="w-full max-w-8 rounded-t-sm bg-primary/70"
                                        style={{ height: `${heightPct}%` }}
                                    />
                                    <span className="text-[9px] text-muted-foreground font-mono">
                                        {new Date(week.week_of).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ))}
        </div>
    );
}

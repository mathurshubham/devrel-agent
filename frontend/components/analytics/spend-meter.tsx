"use client";

function barColorFor(pct: number): string {
    if (pct >= 90) return "bg-red-500";
    if (pct >= 70) return "bg-amber-500";
    return "bg-green-500";
}

export function SpendMeter({
    label,
    usedUsd,
    capUsd,
}: {
    label: string;
    usedUsd: number;
    capUsd: number | null;
}) {
    const hasCap = capUsd !== null && capUsd > 0;
    const pct = hasCap ? Math.min(100, (usedUsd / (capUsd as number)) * 100) : 0;

    return (
        <div className="flex flex-col gap-2 rounded-md border border-border/40 bg-muted/5 p-4">
            <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs font-mono text-muted-foreground">
                    ${usedUsd.toFixed(2)}{hasCap ? ` / $${(capUsd as number).toFixed(2)}` : ""}
                </span>
            </div>
            {hasCap ? (
                <>
                    <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                        <div className={`h-full ${barColorFor(pct)}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[9px] text-muted-foreground font-mono">{pct.toFixed(0)}% of monthly cap</span>
                </>
            ) : (
                <span className="text-[9px] text-muted-foreground font-mono uppercase">No cap configured</span>
            )}
        </div>
    );
}

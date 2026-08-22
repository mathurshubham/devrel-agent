"use client";

function barColorFor(pct: number): string {
    if (pct >= 90) return "bg-red-500";
    if (pct >= 70) return "bg-amber-500";
    return "bg-green-500";
}

function formatAmount(value: number, unit: "usd" | "tokens"): string {
    if (unit === "tokens") return value.toLocaleString();
    return `$${value.toFixed(2)}`;
}

export function SpendMeter({
    label,
    used,
    cap,
    unit = "usd",
    capLabel = "monthly cap",
}: {
    label: string;
    used: number;
    cap: number | null;
    unit?: "usd" | "tokens";
    capLabel?: string;
}) {
    const hasCap = cap !== null && cap > 0;
    const pct = hasCap ? Math.min(100, (used / (cap as number)) * 100) : 0;

    return (
        <div className="flex flex-col gap-2 rounded-md border border-border/40 bg-muted/5 p-4">
            <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{label}</span>
                <span className="text-xs font-mono text-muted-foreground">
                    {formatAmount(used, unit)}{hasCap ? ` / ${formatAmount(cap as number, unit)}` : ""}
                </span>
            </div>
            {hasCap ? (
                <>
                    <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                        <div className={`h-full ${barColorFor(pct)}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[9px] text-muted-foreground font-mono">{pct.toFixed(0)}% of {capLabel}</span>
                </>
            ) : (
                <span className="text-[9px] text-muted-foreground font-mono uppercase">No cap configured</span>
            )}
        </div>
    );
}

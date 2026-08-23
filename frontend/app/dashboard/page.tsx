"use client";

import * as React from "react";
import Link from "next/link";
import { Inbox, Activity, ArrowRight, Gauge, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { useDrafts } from "@/hooks/use-drafts";
import { useCampaigns } from "@/hooks/use-campaigns";
import { useOrgUsage } from "@/hooks/use-vaults";

function StatTile({
    label,
    value,
    isLoading,
    hint,
}: {
    label: string;
    value: React.ReactNode;
    isLoading?: boolean;
    hint?: string;
}) {
    return (
        <Card className="bg-muted/10 border-border/40">
            <CardHeader className="pb-1">
                <CardDescription className="text-[10px] font-mono uppercase tracking-widest">{label}</CardDescription>
            </CardHeader>
            <CardContent>
                {isLoading ? (
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                ) : (
                    <div className="text-2xl font-bold tracking-tight">{value}</div>
                )}
                {hint && <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>}
            </CardContent>
        </Card>
    );
}

function UsageMeter({
    label,
    used,
    max,
    format = (n: number) => n.toLocaleString(),
}: {
    label: string;
    used: number;
    max?: number | null;
    format?: (n: number) => string;
}) {
    const pct = max ? Math.min((used / max) * 100, 100) : 0;
    let color = "bg-green-500";
    if (pct >= 90) color = "bg-red-500";
    else if (pct >= 70) color = "bg-amber-500";

    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-muted-foreground uppercase tracking-wide">{label}</span>
                <span className="font-bold">
                    {format(used)} {max ? `/ ${format(max)}` : "(no cap set)"}
                </span>
            </div>
            <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                <div className={`h-full transition-all duration-500 ${color}`} style={{ width: `${max ? pct : 0}%` }} />
            </div>
        </div>
    );
}

export default function DashboardOverviewPage() {
    const { data: pendingData, isLoading: isLoadingPending } = useDrafts({ status: "PENDING" });
    const { data: awaitingData, isLoading: isLoadingAwaiting } = useDrafts({ status: "AWAITING_CONFIRM" });
    const { data: campaigns, isLoading: isLoadingCampaigns } = useCampaigns();
    const { data: usage, isLoading: isLoadingUsage } = useOrgUsage();

    const activeCount = campaigns?.filter((c) => c.status === "ACTIVE").length ?? 0;
    const pausedCount = campaigns?.filter((c) => c.status === "PAUSED").length ?? 0;

    return (
        <div className="flex flex-col gap-6 p-6 max-w-6xl mx-auto">
            <div>
                <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
                <p className="text-sm text-muted-foreground">
                    Where Sentinel stands right now across your campaigns and inbox.
                </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <StatTile
                    label="Pending Drafts"
                    isLoading={isLoadingPending}
                    value={pendingData?.total ?? 0}
                    hint="Waiting for review"
                />
                <StatTile
                    label="Awaiting Confirmation"
                    isLoading={isLoadingAwaiting}
                    value={awaitingData?.total ?? 0}
                    hint="Copied — waiting on your confirm"
                />
                <StatTile
                    label="Campaigns"
                    isLoading={isLoadingCampaigns}
                    value={campaigns?.length ?? 0}
                    hint={`${activeCount} active · ${pausedCount} paused`}
                />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card className="bg-muted/10 border-border/40">
                    <CardHeader className="flex flex-row items-center justify-between space-y-0">
                        <div className="flex items-center gap-2">
                            <Inbox className="h-4 w-4 text-primary" />
                            <CardTitle className="text-sm">Draft Inbox</CardTitle>
                        </div>
                        <Button size="sm" variant="ghost" className="h-7 text-xs" render={<Link href="/dashboard/inbox" />}>
                            Review <ArrowRight className="ml-1 h-3 w-3" />
                        </Button>
                    </CardHeader>
                    <CardContent>
                        <p className="text-sm text-muted-foreground">
                            {isLoadingPending
                                ? "Loading…"
                                : (pendingData?.total ?? 0) > 0
                                    ? `${pendingData?.total} draft${pendingData?.total === 1 ? "" : "s"} ready for you to open, copy, and post.`
                                    : "Inbox is clear — nothing pending review."}
                        </p>
                    </CardContent>
                </Card>

                <Card className="bg-muted/10 border-border/40">
                    <CardHeader className="flex flex-row items-center justify-between space-y-0">
                        <div className="flex items-center gap-2">
                            <Activity className="h-4 w-4 text-primary" />
                            <CardTitle className="text-sm">Campaigns</CardTitle>
                        </div>
                        <Button size="sm" variant="ghost" className="h-7 text-xs" render={<Link href="/dashboard/campaigns" />}>
                            Manage <ArrowRight className="ml-1 h-3 w-3" />
                        </Button>
                    </CardHeader>
                    <CardContent className="flex items-center gap-2">
                        <Badge className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] font-bold">{activeCount} active</Badge>
                        <Badge variant="outline" className="text-[10px] font-bold">{pausedCount} paused</Badge>
                    </CardContent>
                </Card>
            </div>

            <Card className="bg-muted/10 border-border/40">
                <CardHeader>
                    <div className="flex items-center gap-2">
                        <Gauge className="h-4 w-4 text-primary" />
                        <CardTitle className="text-sm">LLM Spend</CardTitle>
                    </div>
                    <CardDescription className="text-[11px]">Daily tokens and monthly cost against your configured caps.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    {isLoadingUsage ? (
                        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                    ) : usage ? (
                        <>
                            <UsageMeter label="Daily Tokens" used={usage.daily_tokens} max={usage.max_daily_tokens} />
                            <UsageMeter
                                label="Monthly Cost"
                                used={usage.monthly_cost_usd}
                                max={usage.max_monthly_cost}
                                format={(n) => `$${n.toFixed(2)}`}
                            />
                        </>
                    ) : (
                        <p className="text-xs text-muted-foreground">Usage data unavailable.</p>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}

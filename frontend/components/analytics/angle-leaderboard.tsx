"use client";

import * as React from "react";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import type { AngleLeaderboardRow, Platform } from "@/hooks/use-analytics";

const PLATFORM_STYLES: Record<Platform, string> = {
    REDDIT: "bg-orange-500/10 text-orange-500 border-orange-500/20",
    LINKEDIN: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    TWITTER: "bg-sky-500/10 text-sky-500 border-sky-500/20",
};

type SortKey = "drafted" | "posted" | "acceptance_rate" | "avg_engagement";

export function AngleLeaderboard({ angles, platformFilter }: { angles: AngleLeaderboardRow[]; platformFilter: Platform | "ALL" }) {
    const [sortKey, setSortKey] = React.useState<SortKey>("acceptance_rate");
    const [sortDesc, setSortDesc] = React.useState(true);

    const filtered = React.useMemo(
        () => (platformFilter === "ALL" ? angles : angles.filter((a) => a.platform === platformFilter)),
        [angles, platformFilter]
    );

    const sorted = React.useMemo(() => {
        const copy = [...filtered];
        copy.sort((a, b) => (sortDesc ? b[sortKey] - a[sortKey] : a[sortKey] - b[sortKey]));
        return copy;
    }, [filtered, sortKey, sortDesc]);

    const toggleSort = (key: SortKey) => {
        if (key === sortKey) {
            setSortDesc((prev) => !prev);
        } else {
            setSortKey(key);
            setSortDesc(true);
        }
    };

    const SortIcon = ({ column }: { column: SortKey }) => {
        if (column !== sortKey) return <ArrowUpDown className="h-3 w-3 opacity-40" />;
        return sortDesc ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />;
    };

    const headerButton = (label: string, key: SortKey) => (
        <button
            onClick={() => toggleSort(key)}
            className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
            {label}
            <SortIcon column={key} />
        </button>
    );

    if (sorted.length === 0) {
        return (
            <div className="flex items-center justify-center py-16 border border-dashed border-border/60 rounded-md bg-muted/5">
                <p className="text-sm text-muted-foreground">No angle activity recorded yet.</p>
            </div>
        );
    }

    return (
        <div className="border border-border/40 rounded-md overflow-hidden bg-background">
            <div className="overflow-x-auto">
                <Table>
                    <TableHeader className="bg-muted/10">
                        <TableRow className="hover:bg-transparent">
                            <TableHead className="text-[10px] font-mono uppercase tracking-widest py-3">Platform</TableHead>
                            <TableHead className="text-[10px] font-mono uppercase tracking-widest py-3">Angle</TableHead>
                            <TableHead className="py-3">{headerButton("Drafted", "drafted")}</TableHead>
                            <TableHead className="py-3">{headerButton("Posted", "posted")}</TableHead>
                            <TableHead className="py-3">{headerButton("Acceptance", "acceptance_rate")}</TableHead>
                            <TableHead className="py-3">{headerButton("Avg. Engagement", "avg_engagement")}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {sorted.map((angle, idx) => (
                            <TableRow key={`${angle.platform}-${angle.angle}-${idx}`} className="border-border/40">
                                <TableCell>
                                    <Badge variant="outline" className={`text-[9px] font-bold py-0 h-4 ${PLATFORM_STYLES[angle.platform] || ""}`}>
                                        {angle.platform}
                                    </Badge>
                                </TableCell>
                                <TableCell className="text-sm font-medium">{angle.angle}</TableCell>
                                <TableCell className="font-mono text-xs">{angle.drafted}</TableCell>
                                <TableCell className="font-mono text-xs">{angle.posted}</TableCell>
                                <TableCell className="font-mono text-xs font-semibold text-primary">
                                    {(angle.acceptance_rate * 100).toFixed(0)}%
                                </TableCell>
                                <TableCell className="font-mono text-xs">{angle.avg_engagement.toFixed(1)}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

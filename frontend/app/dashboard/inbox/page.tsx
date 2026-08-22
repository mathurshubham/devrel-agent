"use client";

import * as React from "react";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ReviewSheet } from "@/components/drafts/review-sheet";
import { useDrafts, Draft, DraftStatus } from "@/hooks/use-drafts";

const STATUS_FILTERS: { value: DraftStatus | "ALL"; label: string }[] = [
    { value: "ALL", label: "All" },
    { value: "PENDING", label: "Pending" },
    { value: "AWAITING_CONFIRM", label: "Awaiting Confirm" },
    { value: "POSTED", label: "Posted" },
    { value: "REJECTED", label: "Rejected" },
    { value: "IGNORED", label: "Ignored" },
    { value: "FAILED", label: "Failed" },
    { value: "FAILED_COST_LIMIT", label: "Cost Limit" },
];

const StatusBadge = ({ status }: { status: DraftStatus }) => {
    switch (status) {
        case "POSTED":
            return <Badge className="bg-green-500/10 text-green-500 border-green-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">POSTED</Badge>;
        case "AWAITING_CONFIRM":
            return <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">AWAITING CONFIRM</Badge>;
        case "PENDING":
            return <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">PENDING</Badge>;
        case "REJECTED":
            return <Badge variant="destructive" className="bg-red-500/10 text-red-500 border-red-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">REJECTED</Badge>;
        case "IGNORED":
            return <Badge variant="secondary" className="px-1.5 py-0 text-[10px] font-bold tracking-tight opacity-60">IGNORED</Badge>;
        case "FAILED":
        case "FAILED_COST_LIMIT":
            return <Badge variant="destructive" className="bg-red-500/10 text-red-500 border-red-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">{status.replace("_", " ")}</Badge>;
        default:
            return <Badge variant="secondary" className="text-[10px] font-bold tracking-tight">{status}</Badge>;
    }
};

const PlatformBadge = ({ platform }: { platform: Draft["platform"] }) => {
    const styles: Record<string, string> = {
        REDDIT: "bg-orange-500/10 text-orange-500 border-orange-500/20",
        LINKEDIN: "bg-blue-500/10 text-blue-500 border-blue-500/20",
        TWITTER: "bg-sky-500/10 text-sky-500 border-sky-500/20",
    };
    return (
        <Badge variant="outline" className={`px-1.5 py-0 text-[9px] font-bold tracking-tight ${styles[platform] || ""}`}>
            {platform}
        </Badge>
    );
};

const SignalTierBadge = ({ tier }: { tier?: Draft["signal_tier"] }) => {
    if (!tier) return null;
    if (tier === "HIGH") {
        return <Badge className="bg-red-500/10 text-red-500 border-red-500/20 px-1 py-0 text-[9px] font-bold h-4">HIGH</Badge>;
    }
    if (tier === "MEDIUM") {
        return <Badge className="bg-amber-500/10 text-amber-500 border-amber-500/20 px-1 py-0 text-[9px] font-bold h-4">MED</Badge>;
    }
    return <Badge variant="secondary" className="px-1 py-0 text-[9px] font-bold h-4 opacity-50">LOW</Badge>;
};

export default function DraftInboxPage() {
    const [isSheetOpen, setIsSheetOpen] = React.useState(false);
    const [activeDraft, setActiveDraft] = React.useState<Draft | null>(null);
    const [searchInput, setSearchInput] = React.useState("");
    const [debouncedSearch, setDebouncedSearch] = React.useState("");
    const [statusFilter, setStatusFilter] = React.useState<DraftStatus | "ALL">("ALL");

    React.useEffect(() => {
        const timer = setTimeout(() => setDebouncedSearch(searchInput), 400);
        return () => clearTimeout(timer);
    }, [searchInput]);

    const { data, isLoading } = useDrafts({
        q: debouncedSearch || undefined,
        status: statusFilter === "ALL" ? undefined : statusFilter,
    });
    const drafts = data?.items ?? [];

    const handleRowClick = (draft: Draft) => {
        setActiveDraft(draft);
        setIsSheetOpen(true);
    };

    return (
        <div className="flex flex-col h-full bg-background">
            <div className="flex flex-col gap-3 px-6 py-4 border-b border-border/40 bg-background/50 sticky top-0 z-20 backdrop-blur">
                <div className="flex items-center justify-between gap-4">
                    <div className="relative w-full max-w-xl">
                        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                        <Input
                            placeholder="Full-text search (source + draft)..."
                            className="pl-9 h-9 text-sm bg-muted/20 border-border/40"
                            value={searchInput}
                            onChange={(e) => setSearchInput(e.target.value)}
                        />
                    </div>
                    {typeof data?.total === "number" && (
                        <span className="text-[10px] font-mono text-muted-foreground shrink-0">{data.total} total</span>
                    )}
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                    {STATUS_FILTERS.map((f) => (
                        <button
                            key={f.value}
                            onClick={() => setStatusFilter(f.value)}
                            className={`h-6 px-2.5 rounded-full text-[10px] font-bold uppercase tracking-tight border transition-colors ${
                                statusFilter === f.value
                                    ? "bg-primary text-primary-foreground border-primary"
                                    : "bg-muted/20 text-muted-foreground border-border/40 hover:text-foreground"
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="flex-1 overflow-auto">
                <Table className="border-collapse">
                    <TableHeader className="bg-muted/30 sticky top-0 z-10">
                        <TableRow className="hover:bg-transparent border-b border-border/40">
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground py-3 px-6">Status</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Platform</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground w-[360px]">Thread</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Angle</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Signal</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Confidence</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground text-right px-6">Created</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {isLoading ? (
                            Array.from({ length: 6 }).map((_, i) => (
                                <TableRow key={i} className="border-b border-border/40 animate-pulse">
                                    <TableCell className="px-6"><div className="h-5 w-16 bg-muted rounded" /></TableCell>
                                    <TableCell><div className="h-4 w-14 bg-muted rounded" /></TableCell>
                                    <TableCell>
                                        <div className="flex flex-col gap-2">
                                            <div className="h-4 w-64 bg-muted rounded" />
                                            <div className="h-3 w-48 bg-muted rounded" />
                                        </div>
                                    </TableCell>
                                    <TableCell><div className="h-4 w-16 bg-muted rounded" /></TableCell>
                                    <TableCell><div className="h-4 w-10 bg-muted rounded" /></TableCell>
                                    <TableCell><div className="h-4 w-16 bg-muted rounded" /></TableCell>
                                    <TableCell className="text-right px-6"><div className="h-4 w-20 bg-muted rounded ml-auto" /></TableCell>
                                </TableRow>
                            ))
                        ) : drafts.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={7} className="h-64 text-center">
                                    <div className="flex flex-col items-center justify-center gap-2 opacity-50">
                                        <p className="text-sm font-medium">No drafts found</p>
                                        <p className="text-xs">Try a different filter or check back after the next poll.</p>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ) : (
                            drafts.map((draft: Draft) => (
                                <TableRow
                                    key={draft.id}
                                    className="group cursor-pointer hover:bg-muted/40 border-b border-border/40 transition-colors"
                                    onClick={() => handleRowClick(draft)}
                                >
                                    <TableCell className="px-6"><StatusBadge status={draft.status} /></TableCell>
                                    <TableCell><PlatformBadge platform={draft.platform} /></TableCell>
                                    <TableCell>
                                        <div className="flex flex-col gap-0.5">
                                            <span className="text-sm font-semibold truncate max-w-[340px]">{draft.title}</span>
                                            <div className="flex items-center gap-1.5">
                                                <Badge variant="outline" className="text-[9px] px-1 h-3.5 font-mono opacity-50">#{draft.id}</Badge>
                                                <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[200px]">{draft.ai_draft_text?.substring(0, 40) || ''}...</span>
                                            </div>
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <span className="text-[11px] font-mono text-muted-foreground truncate max-w-[120px] block">{draft.angle_name || "—"}</span>
                                    </TableCell>
                                    <TableCell><SignalTierBadge tier={draft.signal_tier} /></TableCell>
                                    <TableCell>
                                        <Popover>
                                            <PopoverTrigger>
                                                <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-2 cursor-help">
                                                    <div className="w-16"><Progress value={(draft.confidence || 0) * 100} className="h-1 bg-muted" /></div>
                                                    <span className={`text-[10px] font-bold font-mono ${draft.confidence > 0.85 ? "text-green-500" : draft.confidence > 0.5 ? "text-amber-500" : "text-red-500"}`}>
                                                        {((draft.confidence || 0) * 100).toFixed(0)}%
                                                    </span>
                                                </div>
                                            </PopoverTrigger>
                                            <PopoverContent className="w-64 p-3 border-border/40 bg-background/95 backdrop-blur" side="top">
                                                <div className="space-y-2">
                                                    <h4 className="text-[10px] font-mono tracking-widest uppercase text-muted-foreground">Triage Reasoning</h4>
                                                    <p className="text-xs">{draft.triage_reasoning || "No reasoning recorded."}</p>
                                                </div>
                                            </PopoverContent>
                                        </Popover>
                                    </TableCell>
                                    <TableCell className="text-right px-6"><span className="text-[11px] font-mono text-muted-foreground tabular-nums">{new Date(draft.created_at).toLocaleString()}</span></TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>

            {activeDraft && <ReviewSheet isOpen={isSheetOpen} onOpenChange={setIsSheetOpen} draft={activeDraft} />}
        </div>
    );
}

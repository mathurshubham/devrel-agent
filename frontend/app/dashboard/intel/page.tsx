"use client";

import * as React from "react";
import { apiErrorText } from "@/hooks/use-api";
import { Radar, Play, Download, Loader2, FileText, TrendingUp, Users } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MarkdownLite } from "@/components/intel/markdown-lite";
import { PillarForecastChart } from "@/components/intel/pillar-forecast";
import { WatchlistPanel } from "@/components/intel/watchlist-panel";
import {
    useAnalystStatus,
    useRunAnalyst,
    useIntelBriefs,
    useIntelBrief,
    usePillarForecast,
    type AnalystRunStatus,
} from "@/hooks/use-analyst";

function StatusChip({ status }: { status: AnalystRunStatus | undefined }) {
    if (!status) return null;
    const styles: Record<AnalystRunStatus, string> = {
        IDLE: "bg-muted text-muted-foreground border-border/40",
        RUNNING: "bg-blue-500/10 text-blue-500 border-blue-500/20",
        COMPLETED: "bg-green-500/10 text-green-500 border-green-500/20",
        FAILED: "bg-red-500/10 text-red-500 border-red-500/20",
    };
    return (
        <Badge variant="outline" className={`text-[10px] uppercase font-mono py-0.5 px-2 ${styles[status]}`}>
            {status === "RUNNING" && <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />}
            {status}
        </Badge>
    );
}

function downloadMarkdown(filename: string, content: string) {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

export default function IntelPage() {
    const { data: status } = useAnalystStatus();
    const runAnalyst = useRunAnalyst();
    const { data: briefs, isLoading: isLoadingBriefs } = useIntelBriefs();
    const { data: forecast, isLoading: isLoadingForecast } = usePillarForecast();

    const [selectedBriefId, setSelectedBriefId] = React.useState<number | null>(null);

    React.useEffect(() => {
        if (!selectedBriefId && briefs && briefs.length > 0) {
            setSelectedBriefId(briefs[0].id);
        }
    }, [briefs, selectedBriefId]);

    const { data: brief, isLoading: isLoadingBrief } = useIntelBrief(selectedBriefId);

    const handleRun = async () => {
        try {
            await runAnalyst.mutateAsync();
            toast.success("Analyst run started — this can take a few minutes.");
        } catch (err: any) {
            if (err?.response?.status === 409) {
                toast.info("The Analyst is already running for this org.");
            } else {
                toast.error(apiErrorText(err, "Failed to start the Analyst run"));
            }
        }
    };

    const handleDownload = () => {
        if (!brief) return;
        downloadMarkdown(`intel-brief-${brief.week_of}.md`, brief.content_md);
    };

    return (
        <div className="flex flex-col gap-6 p-8 max-w-7xl mx-auto">
            <div className="flex items-center justify-between">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 text-foreground">
                        <Radar className="h-5 w-5 text-primary" />
                        <h1 className="text-xl font-semibold tracking-tight">Intel</h1>
                        <StatusChip status={status?.status} />
                    </div>
                    <p className="text-sm text-muted-foreground">
                        Weekly Analyst briefs, pillar-momentum forecast, and watch-list configuration.
                        {status?.week_of && (
                            <span className="ml-1 font-mono text-[11px]">
                                Last run: week of {new Date(status.week_of).toLocaleDateString()}
                            </span>
                        )}
                    </p>
                </div>
                <Button onClick={handleRun} disabled={runAnalyst.isPending || status?.status === "RUNNING"} className="gap-2">
                    {runAnalyst.isPending || status?.status === "RUNNING" ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                        <Play className="h-4 w-4" />
                    )}
                    Run Analyst Now
                </Button>
            </div>

            <Tabs defaultValue="briefs" className="w-full">
                <TabsList className="bg-muted/50 p-1 mb-6">
                    <TabsTrigger value="briefs" className="gap-2">
                        <FileText className="h-3.5 w-3.5" />
                        Briefs
                    </TabsTrigger>
                    <TabsTrigger value="forecast" className="gap-2">
                        <TrendingUp className="h-3.5 w-3.5" />
                        Forecast
                    </TabsTrigger>
                    <TabsTrigger value="watchlist" className="gap-2">
                        <Users className="h-3.5 w-3.5" />
                        Watch List
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="briefs" className="outline-none">
                    <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6">
                        <div className="flex flex-col gap-2 border border-border/40 rounded-md bg-muted/5 p-3 h-fit">
                            <h2 className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground px-1 mb-1">
                                Brief history
                            </h2>
                            {isLoadingBriefs ? (
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mx-auto my-4" />
                            ) : !briefs || briefs.length === 0 ? (
                                <p className="text-xs text-muted-foreground italic px-1 py-2">
                                    No briefs yet. Run the Analyst to generate one.
                                </p>
                            ) : (
                                briefs.map((b) => (
                                    <button
                                        key={b.id}
                                        onClick={() => setSelectedBriefId(b.id)}
                                        className={`text-left rounded-md px-3 py-2 text-xs transition-colors ${
                                            selectedBriefId === b.id
                                                ? "bg-primary/10 text-primary font-medium"
                                                : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                                        }`}
                                    >
                                        <div className="font-mono text-[11px]">Week of {new Date(b.week_of).toLocaleDateString()}</div>
                                    </button>
                                ))
                            )}
                        </div>

                        <div className="border border-border/40 rounded-md bg-background min-h-[400px]">
                            {isLoadingBrief ? (
                                <div className="flex items-center justify-center h-[400px]">
                                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                </div>
                            ) : !brief ? (
                                <div className="flex flex-col items-center justify-center h-[400px] gap-2 text-muted-foreground">
                                    <FileText className="h-8 w-8 opacity-20" />
                                    <p className="text-sm">Select a brief to view it, or run the Analyst to generate the first one.</p>
                                </div>
                            ) : (
                                <div className="flex flex-col">
                                    <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 sticky top-0 bg-background/95 backdrop-blur">
                                        <span className="text-sm font-semibold">
                                            Intel Brief — week of {new Date(brief.week_of).toLocaleDateString()}
                                        </span>
                                        <Button variant="outline" size="sm" className="h-8 text-[10px] uppercase font-mono gap-1.5" onClick={handleDownload}>
                                            <Download className="h-3.5 w-3.5" />
                                            Download .md
                                        </Button>
                                    </div>
                                    <div className="px-6 py-4">
                                        <MarkdownLite content={brief.content_md} />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="forecast" className="outline-none">
                    {isLoadingForecast ? (
                        <div className="flex justify-center py-20">
                            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                        </div>
                    ) : (
                        <PillarForecastChart data={forecast ?? null} />
                    )}
                </TabsContent>

                <TabsContent value="watchlist" className="outline-none">
                    <WatchlistPanel />
                </TabsContent>
            </Tabs>
        </div>
    );
}

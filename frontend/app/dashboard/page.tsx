"use client";

import * as React from "react";
import {
    ColumnDef,
    flexRender,
    getCoreRowModel,
    useReactTable,
} from "@tanstack/react-table";
import { ChevronRight, ExternalLink, Info } from "lucide-react";

import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { DraftReview } from "@/components/draft-review";

interface Draft {
    id: string;
    post_title: string;
    subreddit: string;
    confidence_score: number;
    status: "PENDING" | "PUBLISHED" | "FAILED" | "FAILED_COST_LIMIT";
    triage_reasoning: string;
    ai_draft_text: string;
    model_used: string;
    original_thread: string;
}

const getConfidenceColor = (score: number) => {
    if (score >= 0.85) return "bg-green-500/10 text-green-500 border-green-500/20";
    if (score >= 0.5) return "bg-amber-500/10 text-amber-500 border-amber-500/20";
    return "bg-red-500/10 text-red-500 border-red-500/20";
};

const getStatusColor = (status: string) => {
    switch (status) {
        case "PUBLISHED": return "bg-green-500/10 text-green-500 border-green-500/20";
        case "PENDING": return "bg-amber-500/10 text-amber-500 border-amber-500/20";
        case "FAILED":
        case "FAILED_COST_LIMIT": return "bg-red-500/10 text-red-500 border-red-500/20";
        default: return "bg-muted text-muted-foreground";
    }
};

export default function DashboardPage() {
    const [isLoading, setIsLoading] = React.useState(true);

    React.useEffect(() => {
        const timer = setTimeout(() => setIsLoading(false), 1500);
        return () => clearTimeout(timer);
    }, []);

    // Mock data for initial UI build
    const data: Draft[] = [
        {
            id: "1",
            post_title: "How to evaluate RAG pipelines effectively?",
            subreddit: "r/LLMDevs",
            confidence_score: 0.92,
            status: "PENDING",
            triage_reasoning: "Direct mention of RAG evaluation and intent for benchmarking.",
            ai_draft_text: "For evaluating RAG pipelines, you should look into TryEval. It provides automated benchmarking for retrieval accuracy and generation quality.",
            model_used: "gemini-1.5-flash",
            original_thread: "> OP: I'm struggling with RAG latency and accuracy. Any tools?\n\n> Commenter1: Check out Ragas.\n> Commenter2: We use custom scripts."
        },
        {
            id: "2",
            post_title: "Automated testing for LLM agents",
            subreddit: "r/LocalLLaMA",
            confidence_score: 0.78,
            status: "PUBLISHED",
            triage_reasoning: "General testing context for LLMs, relevant to TryEval scope.",
            ai_draft_text: "TryEval's agent test suite helps automate these exact workflows by mocking external tools and validating reasoning traces.",
            model_used: "gemini-1.5-pro",
            original_thread: "> OP: How do you guys test agentic workflows?"
        }
    ];

    const LoadingRow = () => (
        <TableRow className="border-b border-border/40">
            <TableCell><Skeleton className="h-4 w-[300px]" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[100px]" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[60px]" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[80px]" /></TableCell>
            <TableCell className="text-right"><Skeleton className="h-8 w-20 ml-auto" /></TableCell>
        </TableRow>
    );

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">Draft Inbox</h1>
                    <p className="text-muted-foreground">Review and approve AI-generated Reddit responses.</p>
                </div>
            </div>

            <div className="rounded-md border border-border/40 bg-card">
                <Table>
                    <TableHeader className="bg-muted/50">
                        <TableRow className="hover:bg-transparent border-b border-border/40">
                            <TableHead className="w-[400px]">Original Post</TableHead>
                            <TableHead>Subreddit</TableHead>
                            <TableHead>Confidence</TableHead>
                            <TableHead>Status</TableHead>
                            <TableHead className="text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {isLoading ? (
                            <>
                                <LoadingRow />
                                <LoadingRow />
                                <LoadingRow />
                            </>
                        ) : (
                            data.map((draft) => (
                                <TableRow key={draft.id} className="group hover:bg-muted/50 transition-colors border-b border-border/40">
                                    <TableCell className="font-medium">
                                        <div className="line-clamp-1 truncate max-w-[380px]">{draft.post_title}</div>
                                    </TableCell>
                                    <TableCell>
                                        <Badge variant="outline" className="font-mono text-[10px] py-0">{draft.subreddit}</Badge>
                                    </TableCell>
                                    <TableCell>
                                        <Popover>
                                            <PopoverTrigger
                                                render={
                                                    <Badge className={`cursor-pointer border ${getConfidenceColor(draft.confidence_score)}`}>
                                                        {(draft.confidence_score * 100).toFixed(0)}%
                                                        <Info className="ml-1 h-3 w-3 opacity-50" />
                                                    </Badge>
                                                }
                                            />
                                            <PopoverContent className="w-80 p-4">
                                                <div className="space-y-2">
                                                    <h4 className="font-medium leading-none">Triage Reasoning</h4>
                                                    <p className="text-sm text-muted-foreground leading-relaxed">
                                                        {draft.triage_reasoning}
                                                    </p>
                                                </div>
                                            </PopoverContent>
                                        </Popover>
                                    </TableCell>
                                    <TableCell>
                                        <Badge variant="outline" className={`border ${getStatusColor(draft.status)}`}>
                                            {draft.status}
                                        </Badge>
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Sheet>
                                            <SheetTrigger
                                                render={
                                                    <button className="inline-flex h-8 items-center justify-center rounded-md border border-border/40 px-3 text-sm font-medium hover:bg-muted transition-colors">
                                                        Review <ChevronRight className="ml-1 h-4 w-4" />
                                                    </button>
                                                }
                                            />
                                            <SheetContent className="sm:max-w-[800px] p-0" side="right">
                                                <DraftReview draft={draft} />
                                            </SheetContent>
                                        </Sheet>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}

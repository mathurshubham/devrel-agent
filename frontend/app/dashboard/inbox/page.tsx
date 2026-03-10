"use client";

import * as React from "react";
import {
    Download,
    Search,
    MoreHorizontal,
    ExternalLink,
    Filter,
    ArrowUpDown,
    CheckCircle2,
    Clock,
    AlertCircle
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ReviewSheet } from "@/components/drafts/review-sheet";
import { useDrafts, Draft } from "@/hooks/use-drafts";

// Mock data based on TRD
const drafts = [
    {
        id: "D-1290",
        status: "PENDING",
        subreddit: "r/LLMDevs",
        confidence: 0.91,
        reasoning: ["Mentions RAG", "Benchmarking context", "Evaluation intent"],
        post_title: "Anyone benchmarking RAG pipelines?",
        original_text: "I've been working on a RAG pipeline and I'm struggling with how to properly benchmark the retrieval step. Are there any established frameworks or datasets that people recommend for this specifically?",
        ai_draft_text: "Benchmarking RAG retrieval is indeed a nuanced challenge. You might find TryEval particularly useful for this—it's designed exactly for creating high-fidelity evaluation datasets from your own production logs. For established frameworks, RAGAS is a solid starting point for automated metrics, but having a human-in-the-loop validation set is where TryEval shines.",
        model_used: "gemini-1.5-flash",
        prompt_version: "triage_v2.1",
        created_at: "2 mins ago"
    },
    {
        id: "D-1289",
        status: "PUBLISHED",
        subreddit: "r/LocalLLaMA",
        confidence: 0.88,
        reasoning: ["Local inference optimization", "Hardware query"],
        post_title: "Speeding up Llama 3 on Mac M2",
        original_text: "What are the best quantization methods currently for running Llama 3 8B on an M2 Max? I'm seeing decent performance with GGUF but wondering if there's more I can squeeze out.",
        ai_draft_text: "For Apple Silicon, GGUF remains top-tier due to the Metal support. However, have you tried EXL2? It can sometimes offer better speed/perplexity trade-offs on specific hardware. If you're looking to verify if a specific quantization actually preserves the reasoning logic correctly, that's where evaluation becomes critical.",
        model_used: "gpt-4o",
        prompt_version: "triage_v2.0",
        created_at: "1 hour ago"
    },
    {
        id: "D-1288",
        status: "FAILED_COST_LIMIT",
        subreddit: "r/machinelearning",
        confidence: 0.45,
        reasoning: ["Low intent match", "General discussion"],
        post_title: "State of ML in 2024",
        original_text: "Just a general thread to discuss major breakthroughs this year. What's everyone's favorite paper so far?",
        ai_draft_text: "",
        model_used: "claude-3-5-sonnet",
        prompt_version: "triage_v2.1",
        created_at: "3 hours ago"
    }
];

const StatusBadge = ({ status }: { status: string }) => {
    switch (status) {
        case "PUBLISHED": return <Badge className="bg-green-500/10 text-green-500 border-green-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">PUBLISHED</Badge>;
        case "PENDING": return <Badge variant="outline" className="bg-amber-500/10 text-amber-500 border-amber-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">PENDING</Badge>;
        case "REJECTED": return <Badge variant="destructive" className="bg-red-500/10 text-red-500 border-red-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">REJECTED</Badge>;
        default: return <Badge variant="secondary" className="text-[10px] font-bold tracking-tight">{status}</Badge>;
    }
};

export default function DraftInboxPage() {
    const [selectedDrafts, setSelectedDrafts] = React.useState<number[]>([]);
    const [isSheetOpen, setIsSheetOpen] = React.useState(false);
    const [activeDraft, setActiveDraft] = React.useState<Draft | null>(null);
    const [searchInput, setSearchInput] = React.useState("");
    const [debouncedSearch, setDebouncedSearch] = React.useState("");

    React.useEffect(() => {
        const timer = setTimeout(() => setDebouncedSearch(searchInput), 400);
        return () => clearTimeout(timer);
    }, [searchInput]);

    const { data: drafts = [], isLoading } = useDrafts(debouncedSearch);

    const toggleSelect = (id: number) => {
        setSelectedDrafts(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
    };

    const handleRowClick = (draft: any) => {
        setActiveDraft(draft);
        setIsSheetOpen(true);
    };

    return (
        <div className="flex flex-col h-full bg-background">
            <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 bg-background/50 sticky top-0 z-20 backdrop-blur">
                <div className="flex items-center gap-4 flex-1 max-w-xl">
                    <div className="relative w-full">
                        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                        <Input
                            placeholder="FTS Search drafts (Post content, AI text)..."
                            className="pl-9 h-9 text-sm bg-muted/20 border-border/40"
                            value={searchInput}
                            onChange={(e) => setSearchInput(e.target.value)}
                        />
                    </div>
                </div>
                {selectedDrafts.length > 0 && (
                    <Button variant="default" size="sm" className="h-9 bg-primary text-primary-foreground text-xs font-bold px-4">
                        <Download className="mr-2 h-3.5 w-3.5" />
                        Export to TryEval ({selectedDrafts.length})
                    </Button>
                )}
            </div>

            <div className="flex-1 overflow-auto">
                <Table className="border-collapse">
                    <TableHeader className="bg-muted/30 sticky top-0 z-10">
                        <TableRow className="hover:bg-transparent border-b border-border/40">
                            <TableHead className="w-[40px] px-6">
                                <Checkbox
                                    checked={drafts.length > 0 && selectedDrafts.length === drafts.length}
                                    onCheckedChange={(checked: boolean) => setSelectedDrafts(checked ? drafts.map((d: Draft) => d.id) : [])}
                                />
                            </TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground py-3">Status</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Community</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground w-[400px]">Thread Title</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Confidence</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground text-right px-6">Created</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {isLoading ? (
                            Array.from({ length: 5 }).map((_, i) => (
                                <TableRow key={i} className="border-b border-border/40 animate-pulse">
                                    <TableCell className="px-6"><div className="h-4 w-4 bg-muted rounded" /></TableCell>
                                    <TableCell><div className="h-5 w-16 bg-muted rounded" /></TableCell>
                                    <TableCell><div className="h-4 w-24 bg-muted rounded" /></TableCell>
                                    <TableCell>
                                        <div className="flex flex-col gap-2">
                                            <div className="h-4 w-64 bg-muted rounded" />
                                            <div className="h-3 w-48 bg-muted rounded" />
                                        </div>
                                    </TableCell>
                                    <TableCell><div className="h-4 w-16 bg-muted rounded" /></TableCell>
                                    <TableCell className="text-right px-6"><div className="h-4 w-20 bg-muted rounded ml-auto" /></TableCell>
                                </TableRow>
                            ))
                        ) : (
                            drafts.map((draft: Draft) => (
                                <TableRow
                                    key={draft.id}
                                    className="group cursor-pointer hover:bg-muted/40 border-b border-border/40 transition-colors"
                                    onClick={() => handleRowClick(draft)}
                                >
                                    <TableCell className="px-6" onClick={(e) => e.stopPropagation()}>
                                        <Checkbox checked={selectedDrafts.includes(draft.id)} onCheckedChange={() => toggleSelect(draft.id)} />
                                    </TableCell>
                                    <TableCell><StatusBadge status={draft.status} /></TableCell>
                                    <TableCell className="text-xs font-mono text-muted-foreground">{draft.subreddit}</TableCell>
                                    <TableCell>
                                        <div className="flex flex-col gap-0.5">
                                            <span className="text-sm font-semibold truncate max-w-[350px]">{draft.post_title}</span>
                                            <div className="flex items-center gap-1.5">
                                                <Badge variant="outline" className="text-[9px] px-1 h-3.5 font-mono opacity-50">{draft.id}</Badge>
                                                <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[200px]">{draft.ai_draft_text?.substring(0, 40) || ''}...</span>
                                            </div>
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <Popover>
                                            <PopoverTrigger>
                                                <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-2 cursor-help">
                                                    <div className="w-16"><Progress value={(draft.confidence_score || 0) * 100} className="h-1 bg-muted" /></div>
                                                    <span className={`text-[10px] font-bold font-mono ${draft.confidence_score > 0.85 ? "text-green-500" : draft.confidence_score > 0.5 ? "text-amber-500" : "text-red-500"}`}>
                                                        {((draft.confidence_score || 0) * 100).toFixed(0)}%
                                                    </span>
                                                </div>
                                            </PopoverTrigger>
                                            <PopoverContent className="w-64 p-3 border-border/40 bg-background/95 backdrop-blur" side="top">
                                                <div className="space-y-2">
                                                    <h4 className="text-[10px] font-mono tracking-widest uppercase text-muted-foreground">Triage Reasoning</h4>
                                                    <ul className="space-y-1">
                                                        {draft.triage_reasoning?.split('\n').map((r: string, i: number) => (
                                                            <li key={i} className="text-xs flex items-center gap-2">
                                                                <div className="h-1 w-1 rounded-full bg-primary" />{r}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            </PopoverContent>
                                        </Popover>
                                    </TableCell>
                                    <TableCell className="text-right px-6"><span className="text-[11px] font-mono text-muted-foreground tabular-nums">{draft.created_at}</span></TableCell>
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

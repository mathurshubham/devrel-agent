"use client";

import * as React from "react";
import {
    Send,
    X,
    ExternalLink,
    Info,
    History,
    ShieldCheck,
    MessageSquare,
    Zap,
    Copy,
    Check,
    ShieldAlert,
    BrainCircuit
} from "lucide-react";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
    PopoverHeader,
    PopoverTitle,
} from "@/components/ui/popover";
import { toast } from "sonner";
import { useApproveDraft, useRejectDraft, useLockDraft, Draft } from "@/hooks/use-drafts";

interface ReviewSheetProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    draft: Draft;
}

export function ReviewSheet({ isOpen, onOpenChange, draft }: ReviewSheetProps) {
    const [editedText, setEditedText] = React.useState(draft.ai_draft_text);
    const [copied, setCopied] = React.useState(false);

    const { mutate: approve, isPending: isApproving } = useApproveDraft();
    const { mutate: reject, isPending: isRejecting } = useRejectDraft();
    const { mutate: lock } = useLockDraft();

    const isPending = isApproving || isRejecting;

    React.useEffect(() => {
        setEditedText(draft.ai_draft_text);
        if (isOpen && draft.id) {
            lock(draft.id);
        }
    }, [draft, isOpen]);

    // Keyboard Shortcuts (Section 11)
    React.useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (!isOpen || isPending) return;

            // Avoid triggering when typing in the textarea
            if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) {
                return;
            }

            if (e.key.toLowerCase() === 'a') {
                e.preventDefault();
                handlePublish();
            } else if (e.key.toLowerCase() === 'r') {
                e.preventDefault();
                handleReject();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, isPending, editedText]);

    const handleCopy = () => {
        navigator.clipboard.writeText(editedText);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Draft copied to clipboard");
    };

    const handlePublish = () => {
        approve(draft.id, {
            onSuccess: () => {
                toast.success("Reply approved and queued!");
                onOpenChange(false);
            },
            onError: (error: any) => toast.error(`Approval failed: ${error.message}`),
        });
    };

    const handleReject = () => {
        reject(draft.id, {
            onSuccess: () => {
                toast.success("Draft discarded.");
                onOpenChange(false);
            },
            onError: (error: any) => toast.error(`Rejection failed: ${error.message}`),
        });
    };

    const isSafetyOverride = draft.confidence_score >= 0.9 && draft.status === "PENDING"; // Simplified check for badge demonstration

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent side="right" className="w-[85vw] sm:w-[50vw] p-0 flex flex-col border-l border-border/40 shadow-2xl">
                <SheetHeader className="h-14 px-6 border-b border-border/40 flex flex-row items-center justify-between space-y-0 bg-background/50 backdrop-blur sticky top-0 z-10">
                    <div className="flex items-center gap-3">
                        <SheetTitle className="text-sm font-bold tracking-tight">Review AI Draft</SheetTitle>
                        <Badge variant="outline" className="font-mono text-[9px] h-4 leading-none opacity-50 px-1">{draft.id}</Badge>

                        {isSafetyOverride && (
                            <Badge className="bg-amber-500/10 text-amber-500 border-amber-500/20 text-[9px] font-bold py-0 h-4">
                                <ShieldAlert className="mr-1 h-3 w-3" /> SAFETY OVERRIDE
                            </Badge>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1.5 mr-2">
                            <span className="text-[10px] font-mono text-muted-foreground uppercase opacity-50">Model</span>
                            <Badge variant="secondary" className="text-[10px] py-0 h-4 font-mono px-1.5">{draft.model_used}</Badge>
                        </div>
                        <Button
                            variant="default"
                            size="sm"
                            className="h-8 text-xs font-bold px-4 group/btn"
                            onClick={handlePublish}
                            disabled={isPending}
                        >
                            <Send className="mr-2 h-3 w-3 group-hover/btn:translate-x-0.5 transition-transform" />
                            {isApproving ? "Queueing..." : "Approve & Publish"}
                            <span className="ml-2 opacity-30 text-[10px] hidden sm:inline">[A]</span>
                        </Button>
                    </div>
                </SheetHeader>

                <div className="flex-1 flex overflow-hidden">
                    {/* Left Pane: Source Context */}
                    <div className="flex-1 overflow-y-auto border-r border-border/40 bg-muted/10 p-6 space-y-6">
                        <section>
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                                    <MessageSquare className="h-3 w-3" /> Reddit Context
                                </h3>
                                <a href={draft.reddit_post_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-primary hover:underline flex items-center gap-1 font-medium">
                                    Open Post <ExternalLink className="h-2.5 w-2.5" />
                                </a>
                            </div>
                            <div className="rounded border border-border/40 bg-background p-4 relative overflow-hidden group">
                                <div className="absolute top-0 left-0 w-1 h-full bg-primary/20" />
                                <h4 className="text-sm font-bold mb-3 leading-snug">{draft.post_title}</h4>
                                <blockquote className="text-sm text-foreground/80 font-medium leading-relaxed italic border-l-2 border-primary/10 pl-4 py-1 whitespace-pre-wrap">
                                    {draft.original_text}
                                </blockquote>
                            </div>
                        </section>

                        <section className="space-y-3">
                            <h3 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                                <Zap className="h-3 w-3" /> System Provenance
                            </h3>
                            <div className="grid grid-cols-2 gap-2">
                                <div className="rounded border border-border/40 bg-background p-3">
                                    <span className="text-[9px] font-mono uppercase text-muted-foreground block mb-1">Prompt Version</span>
                                    <span className="text-xs font-bold font-mono">{draft.prompt_template_version}</span>
                                </div>
                                <div className="rounded border border-border/40 bg-background p-3 relative group">
                                    <span className="text-[9px] font-mono uppercase text-muted-foreground block mb-1">Confidence</span>

                                    <Popover>
                                        <PopoverTrigger>
                                            <div className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity">
                                                <Badge className={`${draft.confidence_score > 0.8 ? "bg-green-500/10 text-green-500" : "bg-amber-500/10 text-amber-500"} border-transparent text-[11px] font-bold h-5`}>
                                                    {(draft.confidence_score * 100).toFixed(0)}%
                                                </Badge>
                                                <Info className="h-3 w-3 text-muted-foreground opacity-30" />
                                            </div>
                                        </PopoverTrigger>
                                        <PopoverContent className="w-80">
                                            <PopoverHeader>
                                                <PopoverTitle className="text-xs font-bold flex items-center gap-2">
                                                    <BrainCircuit className="h-3.5 w-3.5 text-primary" />
                                                    Triage Reasoning
                                                </PopoverTitle>
                                            </PopoverHeader>
                                            <div className="text-xs leading-relaxed text-muted-foreground p-1 font-medium italic">
                                                "{draft.triage_reasoning || "No detailed reasoning available for this generation."}"
                                            </div>
                                        </PopoverContent>
                                    </Popover>
                                </div>
                            </div>
                        </section>
                    </div>

                    {/* Right Pane: AI Editor */}
                    <div className="flex-1 flex flex-col overflow-hidden p-6 space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                                <Zap className="h-3 w-3 animate-pulse text-primary fill-primary/20" /> Draft Editor
                            </h3>
                            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopy}>
                                {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
                            </Button>
                        </div>
                        <div className="flex-1 relative">
                            <Textarea
                                value={editedText}
                                onChange={(e) => setEditedText(e.target.value)}
                                className="h-full resize-none border-none p-0 text-sm leading-relaxed focus-visible:ring-0 bg-transparent font-medium"
                                placeholder="Edit your response here..."
                                disabled={isPending}
                            />
                        </div>

                        <div className="pt-4 border-t border-border/40">
                            <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono font-medium">
                                <span>{editedText.length} chars</span>
                                <div className="flex items-center gap-3">
                                    <button
                                        className="hover:text-foreground disabled:opacity-50"
                                        onClick={() => setEditedText(draft.ai_draft_text)}
                                        disabled={isPending}
                                    >Reset</button>
                                    <Separator orientation="vertical" className="h-2" />
                                    <button
                                        className="text-red-500 hover:text-red-400 flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed group/rej"
                                        onClick={handleReject}
                                        disabled={isPending}
                                    >
                                        {isRejecting ? "Discarding..." : "Reject"}
                                        <span className="opacity-30 group-hover/rej:opacity-100 transition-opacity ml-1">[R]</span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}

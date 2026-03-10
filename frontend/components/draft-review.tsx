"use client";

import * as React from "react";
import { Copy, ExternalLink, Send, Check } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

interface DraftReviewProps {
    draft: {
        id: string;
        post_title: string;
        subreddit: string;
        confidence_score: number;
        status: string;
        ai_draft_text: string;
        model_used: string;
        original_thread: string;
    };
}

export function DraftReview({ draft }: DraftReviewProps) {
    const [editedText, setEditedText] = React.useState(draft.ai_draft_text);
    const [isPublishing, setIsPublishing] = React.useState(false);
    const [copied, setCopied] = React.useState(false);

    const handleCopy = () => {
        navigator.clipboard.writeText(JSON.stringify(draft, null, 2));
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Prompt payload copied to clipboard");
    };

    const handlePublish = async () => {
        setIsPublishing(true);
        const toastId = toast.loading("Queued...");

        setTimeout(() => {
            toast.loading("Publishing...", { id: toastId });
            setTimeout(() => {
                toast.success("Published ✓", { id: toastId });
                setIsPublishing(false);
            }, 1500);
        }, 1000);
    };

    return (
        <div className="flex h-full flex-col">
            <div className="flex h-16 items-center justify-between border-b border-border/40 px-6">
                <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold">Review Draft</h2>
                    <Badge variant="outline" className="text-[10px] font-mono">{draft.id}</Badge>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>Model:</span>
                    <Badge variant="secondary" className="text-[10px] px-1">{draft.model_used}</Badge>
                </div>
            </div>

            <div className="flex flex-1 overflow-hidden">
                {/* Left Side: Original Thread */}
                <div className="flex-1 overflow-auto border-r border-border/40 bg-muted/20 p-6">
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Original Thread</h3>
                            <a href="#" className="flex items-center text-[10px] hover:underline">
                                View on Reddit <ExternalLink className="ml-1 h-3 w-3" />
                            </a>
                        </div>
                        <div className="rounded-md border border-border/40 bg-background p-4 shadow-sm">
                            <h4 className="mb-2 font-semibold leading-tight">{draft.post_title}</h4>
                            <div className="whitespace-pre-wrap text-sm text-foreground/80 italic border-l-2 border-primary/20 pl-4 py-1">
                                {draft.original_thread}
                            </div>
                        </div>
                        <div className="rounded-md border border-border/40 bg-muted/30 p-4 text-[11px] font-mono">
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-muted-foreground">SYSTEM PROMPT PREVIEW (JSON)</span>
                                <button onClick={handleCopy} className="hover:text-primary transition-colors">
                                    {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
                                </button>
                            </div>
                            <pre className="overflow-x-auto text-muted-foreground/70">
                                {`{
  "org": "TryEval",
  "persona": "OSS DevRel",
  "goal": "Explain evaluation value",
  "subreddit": "${draft.subreddit}",
  "template_version": "v2.1"
}`}
                            </pre>
                        </div>
                    </div>
                </div>

                {/* Right Side: Editable Draft */}
                <div className="flex-1 overflow-auto p-6">
                    <div className="flex h-full flex-col gap-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">AI Generated Response</h3>
                            <Badge className="text-[10px] bg-green-500/10 text-green-500 border-green-500/20">
                                Confidence: {(draft.confidence_score * 100).toFixed(0)}%
                            </Badge>
                        </div>
                        <Textarea
                            value={editedText}
                            onChange={(e) => setEditedText(e.target.value)}
                            className="flex-1 min-h-[400px] resize-none border-border/40 bg-background p-4 text-sm leading-relaxed focus-visible:ring-primary/20"
                            placeholder="Edit AI draft here..."
                        />
                        <div className="flex flex-col gap-2 pt-4">
                            <div className="flex items-center gap-2">
                                <Badge variant="outline" className="text-[9px] text-muted-foreground">SHIFT + ENTER TO PUBLISH</Badge>
                            </div>
                            <button
                                onClick={handlePublish}
                                disabled={isPublishing}
                                className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                            >
                                {isPublishing ? "Processing..." : (
                                    <>
                                        <span>Publish to Reddit</span>
                                        <Send className="h-4 w-4" />
                                    </>
                                )}
                            </button>
                            <button className="text-xs text-muted-foreground hover:text-foreground py-2 transition-colors">
                                Discard Draft
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

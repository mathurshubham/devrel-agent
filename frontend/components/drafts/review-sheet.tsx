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
    Check
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
import { toast } from "sonner";

interface ReviewSheetProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    draft: {
        id: string;
        post_title: string;
        subreddit: string;
        confidence: number;
        original_text: string;
        ai_draft_text: string;
        model_used: string;
        prompt_version: string;
    };
}

export function ReviewSheet({ isOpen, onOpenChange, draft }: ReviewSheetProps) {
    const [editedText, setEditedText] = React.useState(draft.ai_draft_text);
    const [copied, setCopied] = React.useState(false);

    React.useEffect(() => {
        setEditedText(draft.ai_draft_text);
    }, [draft]);

    const handleCopy = () => {
        navigator.clipboard.writeText(editedText);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Draft copied to clipboard");
    };

    const handlePublish = () => {
        const toastId = toast.loading("Publishing to Reddit...");
        // Simulation
        setTimeout(() => {
            toast.success("Reply published successfully!", { id: toastId });
            onOpenChange(false);
        }, 1500);
    };

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent side="right" className="w-[85vw] sm:w-[50vw] p-0 flex flex-col border-l border-border/40 shadow-2xl">
                <SheetHeader className="h-14 px-6 border-b border-border/40 flex flex-row items-center justify-between space-y-0 bg-background/50 backdrop-blur sticky top-0 z-10">
                    <div className="flex items-center gap-3">
                        <SheetTitle className="text-sm font-bold tracking-tight">Review AI Draft</SheetTitle>
                        <Badge variant="outline" className="font-mono text-[9px] h-4 leading-none opacity-50 px-1">{draft.id}</Badge>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1.5 mr-2">
                            <span className="text-[10px] font-mono text-muted-foreground uppercase opacity-50">Model</span>
                            <Badge variant="secondary" className="text-[10px] py-0 h-4 font-mono px-1.5">{draft.model_used}</Badge>
                        </div>
                        <Button
                            variant="default"
                            size="sm"
                            className="h-8 text-xs font-bold px-4"
                            onClick={handlePublish}
                        >
                            <Send className="mr-2 h-3 w-3" /> Approve & Publish
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
                                <a href="#" className="text-[10px] text-primary hover:underline flex items-center gap-1 font-medium">
                                    Open Post <ExternalLink className="h-2.5 w-2.5" />
                                </a>
                            </div>
                            <div className="rounded border border-border/40 bg-background p-4 relative overflow-hidden group">
                                <div className="absolute top-0 left-0 w-1 h-full bg-primary/20" />
                                <h4 className="text-sm font-bold mb-3 leading-snug">{draft.post_title}</h4>
                                <blockquote className="text-sm text-foreground/80 font-medium leading-relaxed italic border-l-2 border-primary/10 pl-4 py-1">
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
                                    <span className="text-[9px] font-mono uppercase text-muted-foreground block mb-1">Prompt Template</span>
                                    <span className="text-xs font-bold font-mono">{draft.prompt_version}</span>
                                </div>
                                <div className="rounded border border-border/40 bg-background p-3">
                                    <span className="text-[9px] font-mono uppercase text-muted-foreground block mb-1">Inferred Intent</span>
                                    <Badge className="bg-green-500/10 text-green-500 border-green-500/20 text-[9px] py-0 h-4 font-bold">HIGH MATCH</Badge>
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
                            />
                        </div>

                        <div className="pt-4 border-t border-border/40">
                            <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono font-medium">
                                <span>Approx {editedText.split(" ").length} words • {editedText.length} chars</span>
                                <div className="flex items-center gap-3">
                                    <button className="hover:text-foreground">Reset Changes</button>
                                    <Separator orientation="vertical" className="h-2" />
                                    <button className="text-red-500 hover:text-red-400">Discard Draft</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}

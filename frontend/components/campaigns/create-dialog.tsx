"use client";

import * as React from "react";
import { Plus, Loader2 } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { useCreateCampaign } from "@/hooks/use-campaigns";

interface CreateCampaignDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
}

export function CreateCampaignDialog({ isOpen, onOpenChange }: CreateCampaignDialogProps) {
    const [subredditName, setSubredditName] = React.useState("");
    const [keywords, setKeywords] = React.useState("");
    const [negativeKeywords, setNegativeKeywords] = React.useState("");
    const [pollFrequency, setPollFrequency] = React.useState(60);

    const { mutate: createCampaign, isPending } = useCreateCampaign();

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();

        if (!subredditName) {
            toast.error("Subreddit name is required");
            return;
        }

        const keywordsArray = keywords
            .split(",")
            .map((k) => k.trim())
            .filter((k) => k !== "");

        const negKeywordsArray = negativeKeywords
            .split(",")
            .map((k) => k.trim())
            .filter((k) => k !== "");

        createCampaign(
            {
                subreddit_name: subredditName,
                keywords: keywordsArray,
                negative_keywords: negKeywordsArray,
                poll_frequency_minutes: pollFrequency,
            },
            {
                onSuccess: () => {
                    toast.success(`Campaign for r/${subredditName} created!`);
                    onOpenChange(false);
                    // Reset form
                    setSubredditName("");
                    setKeywords("");
                    setNegativeKeywords("");
                    setPollFrequency(60);
                },
                onError: (error: any) => {
                    toast.error(`Failed to create campaign: ${error.message}`);
                },
            }
        );
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[425px] bg-background/95 backdrop-blur border-border/40 shadow-2xl">
                <DialogHeader>
                    <DialogTitle className="text-sm font-bold tracking-tight uppercase">Create New Campaign</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4 py-4">
                    <div className="space-y-2">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                            Subreddit Name
                        </label>
                        <div className="relative">
                            <span className="absolute left-3 top-2.5 text-xs text-muted-foreground font-mono">r/</span>
                            <Input
                                placeholder="LLMDevs"
                                className="pl-7 h-9 text-sm bg-muted/20 border-border/40"
                                value={subredditName}
                                onChange={(e) => setSubredditName(e.target.value)}
                                disabled={isPending}
                            />
                        </div>
                    </div>

                    <div className="space-y-2">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                            Keywords (comma-separated)
                        </label>
                        <Textarea
                            placeholder="RAG, benchmarking, eval, vector search"
                            className="min-h-[80px] text-sm bg-muted/20 border-border/40 resize-none"
                            value={keywords}
                            onChange={(e) => setKeywords(e.target.value)}
                            disabled={isPending}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                            Negative Keywords
                        </label>
                        <Textarea
                            placeholder="spam, blogspam, job post"
                            className="min-h-[60px] text-sm bg-muted/20 border-border/40 resize-none"
                            value={negativeKeywords}
                            onChange={(e) => setNegativeKeywords(e.target.value)}
                            disabled={isPending}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                            Poll Frequency (minutes)
                        </label>
                        <Input
                            type="number"
                            min={5}
                            className="h-9 text-sm bg-muted/20 border-border/40"
                            value={pollFrequency}
                            onChange={(e) => setPollFrequency(parseInt(e.target.value) || 0)}
                            disabled={isPending}
                        />
                    </div>

                    <DialogFooter className="pt-2">
                        <Button
                            type="submit"
                            className="w-full h-9 bg-primary text-primary-foreground text-xs font-bold"
                            disabled={isPending}
                        >
                            {isPending ? (
                                <>
                                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                                    Creating...
                                </>
                            ) : (
                                <>
                                    <Plus className="mr-2 h-3.5 w-3.5" />
                                    Create Campaign
                                </>
                            )}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

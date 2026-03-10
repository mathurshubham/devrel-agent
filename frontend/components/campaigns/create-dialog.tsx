"use client";

import * as React from "react";
import { Plus, Loader2, Sparkles, Settings2 } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { useCreateCampaign } from "@/hooks/use-campaigns";
import { RuleTester } from "./rule-tester";

interface CreateCampaignDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
}

export function CreateCampaignDialog({ isOpen, onOpenChange }: CreateCampaignDialogProps) {
    const [name, setName] = React.useState("");
    const [subredditName, setSubredditName] = React.useState("");
    const [keywords, setKeywords] = React.useState("");
    const [pollFrequency, setPollFrequency] = React.useState(240);
    const [isAutoPilot, setIsAutoPilot] = React.useState(false);
    const [confidenceThreshold, setConfidenceThreshold] = React.useState(0.95);

    const { mutate: createCampaign, isPending } = useCreateCampaign();

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();

        if (!name || !subredditName) {
            toast.error("Name and Subreddit are required");
            return;
        }

        const keywordsArray = keywords
            .split(",")
            .map((k) => k.trim())
            .filter((k) => k !== "");

        createCampaign(
            {
                name: name,
                subreddit_name: subredditName,
                keywords: keywordsArray,
                poll_frequency_minutes: pollFrequency,
                is_auto_pilot_enabled: isAutoPilot,
                auto_pilot_confidence_threshold: confidenceThreshold,
            },
            {
                onSuccess: (data) => {
                    toast.success(`Campaign '${name}' created!`);
                    onOpenChange(false);
                    // Reset form
                    setName("");
                    setSubredditName("");
                    setKeywords("");
                    setPollFrequency(240);
                    setIsAutoPilot(false);
                },
                onError: (error: any) => {
                    toast.error(`Failed to create campaign: ${error.message}`);
                },
            }
        );
    };

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[500px] max-h-[90vh] overflow-y-auto bg-background/95 backdrop-blur border-border/40 shadow-2xl">
                <DialogHeader>
                    <DialogTitle className="text-sm font-bold tracking-tight uppercase flex items-center gap-2">
                        <Settings2 className="h-4 w-4 text-primary" />
                        Create New Campaign
                    </DialogTitle>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-5 py-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                                Campaign Name
                            </label>
                            <Input
                                placeholder="E.g. Vector Search 2024"
                                className="h-9 text-sm bg-muted/20 border-border/40"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                disabled={isPending}
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                                Subreddit
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
                    </div>

                    <div className="space-y-2">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                            Triage Keywords (comma-separated, prefix with regex: for patterns)
                        </label>
                        <Textarea
                            placeholder="RAG, benchmarking, regex:/(agentic|autonomy)/i"
                            className="min-h-[80px] text-sm bg-muted/20 border-border/40 resize-none font-medium"
                            value={keywords}
                            onChange={(e) => setKeywords(e.target.value)}
                            disabled={isPending}
                        />
                    </div>

                    <div className="flex items-center justify-between p-3 rounded-lg border border-border/40 bg-muted/5">
                        <div className="space-y-0.5">
                            <label className="text-xs font-bold flex items-center gap-2">
                                <Sparkles className="h-3.5 w-3.5 text-amber-500" /> Auto-Pilot Mode
                            </label>
                            <p className="text-[10px] text-muted-foreground">Automatically publish drafts with high confidence</p>
                        </div>
                        <Switch
                            checked={isAutoPilot}
                            onCheckedChange={setIsAutoPilot}
                            disabled={isPending}
                        />
                    </div>

                    {isAutoPilot && (
                        <div className="space-y-2 animate-in fade-in slide-in-from-top-1">
                            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                                Confidence Threshold (0.0 - 1.0)
                            </label>
                            <Input
                                type="number"
                                step="0.01"
                                min="0"
                                max="1"
                                className="h-9 text-sm bg-muted/10 border-border/40"
                                value={confidenceThreshold}
                                onChange={(e) => setConfidenceThreshold(parseFloat(e.target.value))}
                                disabled={isPending}
                            />
                        </div>
                    )}

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

                    {/* Rule Tester Integration */}
                    {/* For new campaigns, we can't test against ID yet, so we pass undefined */}
                    {/* In a real app, we might allow testing keywords against text without a campaign ID */}
                    <RuleTester
                        keywords={keywords.split(",").map(k => k.trim())}
                    />

                    <DialogFooter className="pt-2">
                        <Button
                            type="submit"
                            className="w-full h-10 bg-primary text-primary-foreground text-xs font-bold uppercase tracking-wider"
                            disabled={isPending}
                        >
                            {isPending ? (
                                <>
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    Deploying Campaign...
                                </>
                            ) : (
                                <>
                                    <Plus className="mr-2 h-4 w-4" />
                                    Initialize Campaign
                                </>
                            )}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

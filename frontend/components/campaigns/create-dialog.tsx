"use client";

import * as React from "react";
import { Plus, Loader2, Settings2 } from "lucide-react";
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
import { useCreateCampaign, Platform } from "@/hooks/use-campaigns";
import { RuleTester } from "./rule-tester";

interface CreateCampaignDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
}

const PLATFORMS: { id: Platform; label: string; valueLabel: string; valuePlaceholder: string }[] = [
    { id: "REDDIT", label: "Reddit", valueLabel: "Subreddit", valuePlaceholder: "LLMDevs" },
    { id: "LINKEDIN", label: "LinkedIn", valueLabel: "Keyword / Profile / Company URL", valuePlaceholder: "vector search" },
    { id: "TWITTER", label: "X / Twitter", valueLabel: "Search term", valuePlaceholder: "\"RAG pipeline\"" },
];

export function CreateCampaignDialog({ isOpen, onOpenChange }: CreateCampaignDialogProps) {
    const [platform, setPlatform] = React.useState<Platform>("REDDIT");
    const [name, setName] = React.useState("");
    const [value, setValue] = React.useState("");
    const [keywords, setKeywords] = React.useState("");
    const [pollFrequency, setPollFrequency] = React.useState(240);

    const { mutate: createCampaign, isPending } = useCreateCampaign();

    const platformMeta = PLATFORMS.find((p) => p.id === platform)!;

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();

        if (!name || !value) {
            toast.error("Name and target value are required");
            return;
        }

        const keywordsArray = keywords
            .split(",")
            .map((k) => k.trim())
            .filter((k) => k !== "");

        createCampaign(
            {
                name,
                platform,
                value,
                keywords: keywordsArray,
                poll_frequency_minutes: pollFrequency,
            },
            {
                onSuccess: () => {
                    toast.success(`Campaign '${name}' created!`);
                    onOpenChange(false);
                    setName("");
                    setValue("");
                    setKeywords("");
                    setPollFrequency(240);
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
                    <div className="space-y-2">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">
                            Platform
                        </label>
                        <div className="grid grid-cols-3 gap-2">
                            {PLATFORMS.map((p) => (
                                <button
                                    key={p.id}
                                    type="button"
                                    onClick={() => setPlatform(p.id)}
                                    disabled={isPending}
                                    className={`h-9 rounded-md border text-xs font-bold transition-colors ${
                                        platform === p.id
                                            ? "border-primary bg-primary/10 text-primary"
                                            : "border-border/40 bg-muted/20 text-muted-foreground hover:text-foreground"
                                    }`}
                                >
                                    {p.label}
                                </button>
                            ))}
                        </div>
                    </div>

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
                                {platformMeta.valueLabel}
                            </label>
                            <Input
                                placeholder={platformMeta.valuePlaceholder}
                                className="h-9 text-sm bg-muted/20 border-border/40"
                                value={value}
                                onChange={(e) => setValue(e.target.value)}
                                disabled={isPending}
                            />
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

                    {/* Rule Tester Integration — only usable once the campaign has an id */}
                    <RuleTester keywords={keywords.split(",").map((k) => k.trim())} />

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

"use client";

import * as React from "react";
import { BookOpen, Save, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { usePersona, useUpdatePersona } from "@/hooks/use-persona";

const TOKEN_LIMIT = 8000;

function estimateTokens(text?: string): number {
    if (!text) return 0;
    return Math.ceil(text.length / 4);
}

export default function PromptsPage() {
    const { data: persona, isLoading: isFetching } = usePersona();
    const { mutate: updatePersona, isPending: isSaving } = useUpdatePersona();

    const [masterContext, setMasterContext] = React.useState("");
    const [rulesets, setRulesets] = React.useState("");
    const [tone, setTone] = React.useState("");

    React.useEffect(() => {
        if (persona) {
            setMasterContext(persona.master_context || "");
            setRulesets(persona.rulesets_dos_donts || "");
            setTone(persona.tone_guidelines || "");
        }
    }, [persona]);

    const estimatedTokens = estimateTokens(masterContext) + estimateTokens(rulesets) + estimateTokens(tone);
    const progressPercentage = Math.min((estimatedTokens / TOKEN_LIMIT) * 100, 100);

    let progressColor = "bg-green-500";
    if (progressPercentage >= 80) {
        progressColor = "bg-red-500";
    } else if (progressPercentage >= 50) {
        progressColor = "bg-amber-500";
    }

    const isExceeded = estimatedTokens > TOKEN_LIMIT;

    const handleSave = () => {
        if (isExceeded) {
            toast.error("Token limit exceeded. Please reduce the length of your prompts.");
            return;
        }
        updatePersona(
            {
                master_context: masterContext,
                rulesets_dos_donts: rulesets,
                tone_guidelines: tone,
            },
            {
                onSuccess: () => {
                    toast.success("Persona saved successfully");
                },
                onError: (error: Error) => {
                    toast.error(`Failed to save persona: ${error.message}`);
                },
            }
        );
    };

    if (isFetching) {
        return (
            <div className="flex flex-col h-full bg-background items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-background">
            <div className="flex flex-col border-b border-border/40 bg-background/50 sticky top-0 z-20 backdrop-blur">
                <div className="flex items-center justify-between px-6 py-4">
                    <div className="flex items-center gap-4">
                        <h1 className="text-sm font-bold tracking-tight uppercase flex items-center gap-2">
                            <BookOpen className="h-4 w-4 text-primary" />
                            Prompt Library & Persona
                        </h1>
                    </div>
                    <Button
                        onClick={handleSave}
                        disabled={isSaving || isExceeded}
                        size="sm"
                        className="h-9 bg-primary text-primary-foreground text-xs font-bold px-4"
                    >
                        {isSaving ? (
                            <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                        ) : (
                            <Save className="mr-2 h-3.5 w-3.5" />
                        )}
                        Save Persona
                    </Button>
                </div>

                <div className="px-6 pb-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Token Context Guard</span>
                        <div className="flex items-center gap-2">
                            {isExceeded && (
                                <span className="text-[10px] font-bold uppercase text-red-500 flex items-center gap-1">
                                    <AlertTriangle className="h-3 w-3" /> Exceeded by {estimatedTokens - TOKEN_LIMIT} tokens
                                </span>
                            )}
                            <span className="text-xs font-mono font-medium">
                                {estimatedTokens.toLocaleString()} / {TOKEN_LIMIT.toLocaleString()} tokens
                            </span>
                        </div>
                    </div>
                    <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div
                            className={`h-full w-full flex-1 transition-all ${progressColor}`}
                            style={{ transform: `translateX(-${100 - progressPercentage}%)` }}
                        />
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-auto p-6">
                <div className="grid grid-cols-1 gap-6 max-w-4xl mx-auto">
                    <div className="flex flex-col gap-2">
                        <h2 className="text-sm font-bold tracking-tight uppercase">Master Context</h2>
                        <p className="text-xs text-muted-foreground">Who are we and what is our product? Add your elevator pitch and competitive advantages.</p>
                        <Textarea
                            placeholder="e.g., We are Sentinel, an open-source Developer Relations AI agent..."
                            value={masterContext}
                            onChange={(e) => setMasterContext(e.target.value)}
                            className="font-mono text-sm leading-relaxed min-h-[200px] border-border/40 bg-muted/20"
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <h2 className="text-sm font-bold tracking-tight uppercase">Rulesets (Do&apos;s & Don&apos;ts)</h2>
                        <p className="text-xs text-muted-foreground">Technical boundaries and support rules. What must the agent always do, and never do?</p>
                        <Textarea
                            placeholder="e.g., DO: Recommend reading the docs. DON'T: Compare with Competitor X."
                            value={rulesets}
                            onChange={(e) => setRulesets(e.target.value)}
                            className="font-mono text-sm leading-relaxed min-h-[200px] border-border/40 bg-muted/20"
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <h2 className="text-sm font-bold tracking-tight uppercase">Tone Guidelines</h2>
                        <p className="text-xs text-muted-foreground">How do we speak? (e.g., helpful, concise, no marketing fluff).</p>
                        <Textarea
                            placeholder="e.g., Speak as a senior software engineer. Be direct, concise, and helpful. Do not use marketing jargon."
                            value={tone}
                            onChange={(e) => setTone(e.target.value)}
                            className="font-mono text-sm leading-relaxed min-h-[200px] border-border/40 bg-muted/20 mb-12"
                        />
                    </div>
                </div>
            </div>
        </div>
    );
}

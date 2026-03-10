"use client";

import * as React from "react";
import { Zap, AlertCircle, CheckCircle2, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { useRuleTester } from "@/hooks/use-campaigns";
import { toast } from "sonner";

interface RuleTesterProps {
    campaignId?: number;
    keywords: string[];
}

export function RuleTester({ campaignId, keywords }: RuleTesterProps) {
    const [sampleText, setSampleText] = React.useState("");
    const { mutate: testRules, data, isPending } = useRuleTester(campaignId || 0);

    const handleTest = () => {
        if (!sampleText) {
            toast.error("Please provide sample text to test");
            return;
        }
        if (!campaignId) {
            // If it's a new campaign, we might need a workaround or just wait for it to be created
            // For now, assume id exists or show a message
            toast.info("Rule testing is available after campaign creation or for existing campaigns.");
            return;
        }
        testRules(sampleText);
    };

    return (
        <div className="space-y-4 pt-4 border-t border-border/40">
            <div className="flex items-center justify-between">
                <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                    <Zap className="h-3 w-3 text-primary fill-primary/20" /> Triage Rule Tester
                </label>
                <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-[9px] font-bold uppercase tracking-tight"
                    onClick={handleTest}
                    disabled={isPending || !campaignId}
                >
                    {isPending ? "Testing..." : "Run Dry-Run"}
                </Button>
            </div>

            <Textarea
                placeholder="Paste a sample Reddit post or comment here to test your keywords and regex..."
                className="min-h-[100px] text-xs bg-muted/10 border-border/40 resize-none font-medium leading-relaxed"
                value={sampleText}
                onChange={(e) => setSampleText(e.target.value)}
            />

            {data && data.results && data.results[0] && (
                <div className="rounded border border-border/40 bg-muted/5 p-3 space-y-3 animate-in fade-in slide-in-from-top-1">
                    <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-medium text-muted-foreground uppercase opacity-70">
                            Evaluation Result
                        </span>
                        {data.results[0].would_trigger ? (
                            <Badge className="bg-green-500/10 text-green-500 border-green-500/20 text-[9px] font-bold py-0 h-4">
                                <CheckCircle2 className="mr-1 h-2.5 w-2.5" /> WOULD TRIGGER
                            </Badge>
                        ) : (
                            <Badge variant="outline" className="text-[9px] font-bold py-0 h-4 opacity-50">
                                <AlertCircle className="mr-1 h-2.5 w-2.5" /> NO MATCH
                            </Badge>
                        )}
                    </div>

                    <div className="space-y-2">
                        <div className="flex flex-wrap gap-1">
                            {data.results[0].matched_keywords.length > 0 ? (
                                data.results[0].matched_keywords.map((kw, i) => (
                                    <Badge key={i} variant="secondary" className="text-[9px] px-1 py-0 h-3.5 font-mono lowercase">
                                        {kw}
                                    </Badge>
                                ))
                            ) : (
                                <span className="text-[10px] text-muted-foreground italic">No keywords matched</span>
                            )}
                        </div>

                        <p className="text-[11px] leading-relaxed text-foreground/80 font-medium italic border-l border-primary/20 pl-2 py-0.5">
                            "{data.results[0].triage_reasoning}"
                        </p>

                        {data.results[0].safety_override && (
                            <div className="flex items-center gap-1 text-[9px] font-bold text-amber-500 bg-amber-500/10 px-1.5 py-0.5 rounded">
                                <ShieldAlert className="h-2.5 w-2.5" /> SAFETY OVERRIDE ACTIVE (Review Required)
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

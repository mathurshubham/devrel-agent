"use client";

import * as React from "react";
import { BookOpen, Save, AlertTriangle, Loader2, Plus, Trash2, History, Shield, BrainCircuit } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { usePersona, useUpdatePersona } from "@/hooks/use-persona";
import { usePrompts, useCreatePrompt, useUpdatePrompt, useDeletePrompt } from "@/hooks/use-prompts";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "@/components/ui/tabs";
import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";

const TOKEN_LIMIT = 8000;

function estimateTokens(text?: string): number {
    if (!text) return 0;
    return Math.ceil(text.length / 4);
}

export default function PromptsPage() {
    const { data: persona, isLoading: isPersonaLoading } = usePersona();
    const { mutate: updatePersona, isPending: isSavingPersona } = useUpdatePersona();

    const { data: prompts, isLoading: isPromptsLoading } = usePrompts();
    const { mutate: createPrompt, isPending: isCreatingPrompt } = useCreatePrompt();
    const { mutate: updatePrompt, isPending: isUpdatingPrompt } = useUpdatePrompt();
    const { mutate: deletePrompt } = useDeletePrompt();

    // Persona State
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
    if (progressPercentage >= 80) progressColor = "bg-red-500";
    else if (progressPercentage >= 50) progressColor = "bg-amber-500";

    const isExceeded = estimatedTokens > TOKEN_LIMIT;

    const handleSavePersona = () => {
        if (isExceeded) {
            toast.error("Token limit exceeded.");
            return;
        }
        updatePersona(
            {
                master_context: masterContext,
                rulesets_dos_donts: rulesets,
                tone_guidelines: tone,
            },
            {
                onSuccess: () => toast.success("Persona updated"),
                onError: (e) => toast.error(`Save failed: ${e.message}`),
            }
        );
    };

    if (isPersonaLoading || isPromptsLoading) {
        return (
            <div className="flex flex-col h-full items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-background overflow-hidden">
            <div className="border-b border-border/40 bg-background/50 backdrop-blur shrink-0">
                <div className="px-6 py-4 flex items-center justify-between">
                    <h1 className="text-sm font-bold tracking-tight uppercase flex items-center gap-2">
                        <BookOpen className="h-4 w-4 text-primary" />
                        Prompt & Persona Engineering
                    </h1>
                </div>
            </div>

            <Tabs defaultValue="persona" className="flex-1 flex flex-col overflow-hidden">
                <div className="px-6 border-b border-border/40 bg-background/50 backdrop-blur shrink-0">
                    <TabsList className="h-10 bg-transparent gap-6">
                        <TabsTrigger value="persona" className="bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none px-0 text-xs font-bold transition-all">
                            AI PERSONA
                        </TabsTrigger>
                        <TabsTrigger value="library" className="bg-transparent border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none px-0 text-xs font-bold transition-all">
                            TEMPLATE LIBRARY
                        </TabsTrigger>
                    </TabsList>
                </div>

                <TabsContent value="persona" className="flex-1 overflow-auto m-0 p-6">
                    <div className="max-w-4xl mx-auto space-y-8">
                        <section className="space-y-4">
                            <div className="flex items-center justify-between">
                                <div className="space-y-1">
                                    <h3 className="text-sm font-bold uppercase tracking-tight flex items-center gap-2">
                                        <Shield className="h-4 w-4 text-primary" /> Core Identity
                                    </h3>
                                    <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-mono">Master context and guardrails for all generations</p>
                                </div>
                                <Button onClick={handleSavePersona} disabled={isSavingPersona || isExceeded} size="sm" className="h-8 text-[10px] font-bold px-4">
                                    {isSavingPersona ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : <Save className="mr-2 h-3 w-3" />}
                                    COMMIT PERSONA
                                </Button>
                            </div>

                            <div className="space-y-4">
                                <div className="space-y-2">
                                    <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">Master Context (Identity)</label>
                                    <Textarea
                                        value={masterContext}
                                        onChange={(e) => setMasterContext(e.target.value)}
                                        className="font-medium text-sm leading-relaxed min-h-[180px] border-border/40 bg-muted/10"
                                        placeholder="We are Sentinel, an open-source DevRel agent specializing in RAG and Evals..."
                                    />
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">Rulesets (Guardrails)</label>
                                        <Textarea
                                            value={rulesets}
                                            onChange={(e) => setRulesets(e.target.value)}
                                            className="font-medium text-sm leading-relaxed min-h-[250px] border-border/40 bg-muted/10 shadow-inner"
                                            placeholder="DO: Point to github.com/shubham/sentinel for code. DON'T: Give legal advice."
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">Tone Guidelines (Voice)</label>
                                        <Textarea
                                            value={tone}
                                            onChange={(e) => setTone(e.target.value)}
                                            className="font-medium text-sm leading-relaxed min-h-[250px] border-border/40 bg-muted/10 shadow-inner"
                                            placeholder="Professional but helpful. senior engineer to developer peer vibe."
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="p-4 rounded-lg border border-border/40 bg-muted/5 space-y-3">
                                <div className="flex items-center justify-between">
                                    <span className="text-[10px] font-mono font-bold uppercase tracking-widest text-muted-foreground">Context Window Guard</span>
                                    <span className="text-[10px] font-mono font-bold">{estimatedTokens.toLocaleString()} / {TOKEN_LIMIT.toLocaleString()} TOKENS</span>
                                </div>
                                <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                                    <div className={`h-full transition-all duration-500 ${progressColor}`} style={{ width: `${progressPercentage}%` }} />
                                </div>
                                {isExceeded && (
                                    <p className="text-[10px] text-red-500 font-bold flex items-center gap-1 uppercase">
                                        <AlertTriangle className="h-3 w-3" /> Warning: Context window exceeded. High risk of hallucination or truncation.
                                    </p>
                                )}
                            </div>
                        </section>
                    </div>
                </TabsContent>

                <TabsContent value="library" className="flex-1 overflow-auto m-0 p-6">
                    <div className="max-w-5xl mx-auto space-y-6">
                        <div className="flex items-center justify-between">
                            <div className="space-y-1">
                                <h3 className="text-sm font-bold uppercase tracking-tight flex items-center gap-2">
                                    <BrainCircuit className="h-4 w-4 text-primary" /> Template Library
                                </h3>
                                <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-mono">Specialized prompts for different community engagement styles</p>
                            </div>
                            <Button size="sm" className="h-8 text-[10px] font-bold px-4">
                                <Plus className="mr-2 h-3 w-3" /> NEW TEMPLATE
                            </Button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {prompts?.map((prompt) => (
                                <Card key={prompt.id} className="bg-muted/5 border-border/40 hover:bg-muted/10 transition-colors group">
                                    <CardHeader className="pb-3 flex flex-row items-center justify-between space-y-0">
                                        <div className="space-y-1">
                                            <CardTitle className="text-xs font-bold uppercase tracking-tight flex items-center gap-2">
                                                {prompt.title}
                                                {prompt.is_system_default && (
                                                    <Badge variant="outline" className="text-[9px] font-bold h-4 border-primary/20 bg-primary/5 text-primary">SYSTEM</Badge>
                                                )}
                                            </CardTitle>
                                            <CardDescription className="text-[10px] font-mono">v{prompt.version}</CardDescription>
                                        </div>
                                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <Button variant="ghost" size="icon" className="h-7 w-7"><History className="h-3 w-3" /></Button>
                                            {!prompt.is_system_default && (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-7 w-7 text-red-500"
                                                    onClick={() => deletePrompt(prompt.id)}
                                                >
                                                    <Trash2 className="h-3 w-3" />
                                                </Button>
                                            )}
                                        </div>
                                    </CardHeader>
                                    <CardContent className="pb-4">
                                        <Textarea
                                            defaultValue={prompt.prompt_body}
                                            className="text-[11px] font-mono leading-relaxed h-[120px] bg-background/50 border-border/20 resize-none"
                                            readOnly={prompt.is_system_default}
                                        />
                                    </CardContent>
                                    <CardFooter className="pt-0 border-t border-border/10 mt-2 py-3 flex justify-between bg-muted/20">
                                        <span className="text-[9px] font-mono text-muted-foreground">Version {prompt.version}</span>
                                        {!prompt.is_system_default && (
                                            <Button variant="ghost" size="sm" className="h-6 text-[9px] font-bold uppercase">Update</Button>
                                        )}
                                    </CardFooter>
                                </Card>
                            ))}
                        </div>
                    </div>
                </TabsContent>
            </Tabs>
        </div>
    );
}

"use client";

import * as React from "react";
import { apiErrorText } from "@/hooks/use-api";
import { BookOpen, Save, AlertTriangle, Loader2, Plus, Trash2, Shield, BrainCircuit, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { usePersona, useUpdatePersona } from "@/hooks/use-persona";
import {
    usePrompts,
    useCreatePrompt,
    useUpdatePrompt,
    useDeletePrompt,
    PromptTemplate,
    Platform,
    PromptType,
} from "@/hooks/use-prompts";
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
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from "@/components/ui/dialog";

const TOKEN_LIMIT = 8000;
const PLATFORMS: Platform[] = ["REDDIT", "LINKEDIN", "TWITTER"];
const TYPES: PromptType[] = ["MASTER_CONTEXT", "ANGLE", "SCOUT", "ANALYST"];

function estimateTokens(text?: string): number {
    if (!text) return 0;
    return Math.ceil(text.length / 4);
}

function NewTemplateDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
    const { mutate: createPrompt, isPending } = useCreatePrompt();
    const [name, setName] = React.useState("");
    const [platform, setPlatform] = React.useState<Platform>("REDDIT");
    const [type, setType] = React.useState<PromptType>("ANGLE");
    const [content, setContent] = React.useState("");

    const reset = () => {
        setName("");
        setPlatform("REDDIT");
        setType("ANGLE");
        setContent("");
    };

    const handleSubmit = () => {
        if (!name.trim() || !content.trim()) {
            toast.error("Name and content are required");
            return;
        }
        createPrompt(
            { name: name.trim(), platform, type, content },
            {
                onSuccess: () => {
                    toast.success("Template created");
                    onOpenChange(false);
                    reset();
                },
                onError: (err: any) => toast.error(apiErrorText(err, "Failed to create template")),
            }
        );
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-lg">
                <DialogHeader>
                    <DialogTitle className="text-sm font-bold uppercase tracking-tight">New Template</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4">
                    <div className="space-y-1.5">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Name</label>
                        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Practitioner Voice Filter" className="h-9 text-sm" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Platform</label>
                            <select
                                value={platform}
                                onChange={(e) => setPlatform(e.target.value as Platform)}
                                className="h-9 w-full rounded-md border border-border/40 bg-background px-2 text-sm"
                            >
                                {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
                            </select>
                        </div>
                        <div className="space-y-1.5">
                            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Type</label>
                            <select
                                value={type}
                                onChange={(e) => setType(e.target.value as PromptType)}
                                className="h-9 w-full rounded-md border border-border/40 bg-background px-2 text-sm"
                            >
                                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Content</label>
                        <Textarea
                            value={content}
                            onChange={(e) => setContent(e.target.value)}
                            className="min-h-[160px] text-sm font-mono"
                            placeholder="Prompt content..."
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="ghost" size="sm" onClick={() => { onOpenChange(false); reset(); }}>Cancel</Button>
                    <Button size="sm" onClick={handleSubmit} disabled={isPending}>
                        {isPending ? "Creating..." : "Create Template"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function TemplateCard({ prompt }: { prompt: PromptTemplate }) {
    const { mutate: updatePrompt, isPending: isUpdating } = useUpdatePrompt();
    const { mutate: createPrompt, isPending: isCopying } = useCreatePrompt();
    const { mutate: deletePrompt } = useDeletePrompt();

    const isSystem = prompt.org_id === null;
    const [content, setContent] = React.useState(prompt.content);
    const isDirty = content !== prompt.content;

    React.useEffect(() => setContent(prompt.content), [prompt.content]);

    const handleUpdate = () => {
        updatePrompt(
            { id: prompt.id, content },
            {
                onSuccess: () => toast.success(`"${prompt.name}" updated to v${prompt.version + 1}`),
                onError: (err: any) => toast.error(apiErrorText(err, "Update failed")),
            }
        );
    };

    const handleCustomize = () => {
        createPrompt(
            {
                name: `${prompt.name} (custom)`,
                platform: prompt.platform,
                type: prompt.type,
                content: prompt.content,
            },
            {
                onSuccess: () => toast.success("Created an editable org copy"),
                onError: (err: any) => toast.error(apiErrorText(err, "Failed to customize")),
            }
        );
    };

    return (
        <Card className="bg-muted/5 border-border/40 hover:bg-muted/10 transition-colors group">
            <CardHeader className="pb-3 flex flex-row items-center justify-between space-y-0">
                <div className="space-y-1">
                    <CardTitle className="text-xs font-bold uppercase tracking-tight flex items-center gap-2">
                        {prompt.name}
                        {isSystem && (
                            <Badge variant="outline" className="text-[9px] font-bold h-4 border-primary/20 bg-primary/5 text-primary">SYSTEM</Badge>
                        )}
                    </CardTitle>
                    <CardDescription className="text-[10px] font-mono">{prompt.platform} · {prompt.type} · v{prompt.version}</CardDescription>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {!isSystem && (
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
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="text-[11px] font-mono leading-relaxed h-[120px] bg-background/50 border-border/20 resize-none"
                    readOnly={isSystem}
                />
            </CardContent>
            <CardFooter className="pt-0 border-t border-border/10 mt-2 py-3 flex justify-between bg-muted/20">
                <span className="text-[9px] font-mono text-muted-foreground">Version {prompt.version}</span>
                {isSystem ? (
                    <Button variant="ghost" size="sm" className="h-6 text-[9px] font-bold uppercase" onClick={handleCustomize} disabled={isCopying}>
                        <Copy className="mr-1 h-2.5 w-2.5" />
                        {isCopying ? "Copying..." : "Customize Copy"}
                    </Button>
                ) : (
                    <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-[9px] font-bold uppercase"
                        onClick={handleUpdate}
                        disabled={isUpdating || !isDirty}
                    >
                        {isUpdating ? "Saving..." : "Update"}
                    </Button>
                )}
            </CardFooter>
        </Card>
    );
}

export default function PromptsPage() {
    const { data: persona, isLoading: isPersonaLoading } = usePersona();
    const { mutate: updatePersona, isPending: isSavingPersona } = useUpdatePersona();

    const { data: prompts, isLoading: isPromptsLoading } = usePrompts();
    const [isNewTemplateOpen, setIsNewTemplateOpen] = React.useState(false);

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
                                <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-mono">Master context, angles, scout & analyst prompts per platform</p>
                            </div>
                            <Button size="sm" className="h-8 text-[10px] font-bold px-4" onClick={() => setIsNewTemplateOpen(true)}>
                                <Plus className="mr-2 h-3 w-3" /> NEW TEMPLATE
                            </Button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {prompts?.map((prompt) => (
                                <TemplateCard key={prompt.id} prompt={prompt} />
                            ))}
                        </div>
                    </div>
                </TabsContent>
            </Tabs>

            <NewTemplateDialog open={isNewTemplateOpen} onOpenChange={setIsNewTemplateOpen} />
        </div>
    );
}

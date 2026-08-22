"use client";

import { useState, useEffect } from "react";
import {
    Key,
    Bot,
    Loader2,
    Settings,
    Users,
    CreditCard,
    History,
    AlertTriangle,
    Zap,
    Database,
    Plus,
    Trash2,
    Pencil,
    ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";
import { OrganizationProfile } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from "@/components/ui/dialog";
import {
    useVaultStatus,
    useUpdateLLMConfig,
    useAuditLogs,
    useKillSwitch,
    LLMProvider,
} from "@/hooks/use-vaults";
import {
    useApifyTokens,
    useApifyCredits,
    useAddApifyToken,
    useUpdateApifyToken,
    useDeleteApifyToken,
} from "@/hooks/use-apify";

const PROVIDERS: { id: LLMProvider; name: string; placeholder: string; hint: string; isDefault?: boolean }[] = [
    { id: "openrouter", name: "OpenRouter", placeholder: "sk-or-...", hint: "openrouter/anthropic/claude-3.5-sonnet", isDefault: true },
    { id: "openai", name: "OpenAI", placeholder: "sk-...", hint: "gpt-4o, gpt-4-turbo" },
    { id: "anthropic", name: "Anthropic", placeholder: "sk-ant-...", hint: "claude-3-5-sonnet-20241022" },
    { id: "gemini", name: "Google Gemini", placeholder: "AIza...", hint: "gemini/gemini-1.5-pro" },
    { id: "ollama", name: "Ollama (self-hosted)", placeholder: "not required", hint: "llama3.1 — requires a base URL" },
    { id: "custom", name: "Custom (OpenAI-compatible)", placeholder: "sk-...", hint: "requires a base URL" },
];

function ApifyKeysTab() {
    const { data: tokens, isLoading: isLoadingTokens } = useApifyTokens();
    const { data: credits } = useApifyCredits();
    const addToken = useAddApifyToken();
    const updateToken = useUpdateApifyToken();
    const deleteToken = useDeleteApifyToken();

    const [label, setLabel] = useState("");
    const [token, setToken] = useState("");
    const [editingCapId, setEditingCapId] = useState<number | null>(null);
    const [capValue, setCapValue] = useState("");
    const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

    const handleAdd = async () => {
        if (!label.trim()) {
            toast.error("Give this token a label");
            return;
        }
        if (!token.startsWith("apify_api_")) {
            toast.error("Apify tokens start with 'apify_api_'");
            return;
        }
        try {
            await addToken.mutateAsync({ label: label.trim(), token: token.trim() });
            toast.success("Apify token added");
            setLabel("");
            setToken("");
        } catch (err: any) {
            toast.error(err?.response?.data?.detail || "Failed to add token");
        }
    };

    const handleSaveCap = async (id: number) => {
        const parsed = parseFloat(capValue);
        if (Number.isNaN(parsed) || parsed <= 0) {
            toast.error("Enter a valid cap amount");
            return;
        }
        try {
            await updateToken.mutateAsync({ id, plan_cap_usd: parsed });
            toast.success("Plan cap updated");
            setEditingCapId(null);
        } catch (err: any) {
            toast.error(err?.response?.data?.detail || "Failed to update cap");
        }
    };

    const handleDelete = async (id: number) => {
        try {
            await deleteToken.mutateAsync(id);
            toast.success("Token removed");
        } catch (err: any) {
            toast.error(err?.response?.data?.detail || "Failed to remove token");
        } finally {
            setDeleteTarget(null);
        }
    };

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="flex flex-col gap-4 border border-border/40 bg-muted/10 rounded-md p-6">
                <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Add a token</h2>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Up to 10 Apify tokens per org. Tokens are Fernet-encrypted at rest and never re-displayed after save —
                    only a masked value is shown.
                </p>
                <div className="flex flex-col gap-2">
                    <Input
                        placeholder="Label (e.g. Free tier #1)"
                        className="h-9 text-sm"
                        value={label}
                        onChange={(e) => setLabel(e.target.value)}
                    />
                    <Input
                        type="password"
                        placeholder="apify_api_..."
                        className="h-9 text-sm font-mono"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                    />
                    <Button size="sm" className="h-8 text-[10px] uppercase font-mono" onClick={handleAdd} disabled={addToken.isPending}>
                        <Plus className="mr-1.5 h-3 w-3" />
                        {addToken.isPending ? "Adding..." : "Add Token"}
                    </Button>
                </div>
            </div>

            <div className="flex flex-col gap-4 border border-border/40 bg-muted/10 rounded-md p-6">
                <div className="flex items-center gap-2">
                    <Zap className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Token vault</h2>
                </div>

                {isLoadingTokens ? (
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                ) : !tokens || tokens.length === 0 ? (
                    <p className="text-xs text-muted-foreground italic">No Apify tokens yet.</p>
                ) : (
                    <div className="flex flex-col gap-3">
                        {tokens.map((t) => {
                            const credit = credits?.find((c) => c.token_id === t.id);
                            let barColor = "bg-green-500";
                            if (credit && credit.pct >= 90) barColor = "bg-red-500";
                            else if (credit && credit.pct >= 70) barColor = "bg-amber-500";

                            return (
                                <div key={t.id} className="rounded-md border border-border/40 bg-background p-3 space-y-2">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-medium">{t.label}</span>
                                            <Badge variant="outline" className="text-[9px] font-mono py-0 h-4">{t.masked}</Badge>
                                            {!t.is_active && (
                                                <Badge variant="secondary" className="text-[9px] py-0 h-4">Inactive</Badge>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-1">
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="h-6 w-6"
                                                onClick={() => { setEditingCapId(t.id); setCapValue(String(t.plan_cap_usd)); }}
                                            >
                                                <Pencil className="h-3 w-3" />
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="h-6 w-6 text-red-500"
                                                onClick={() => setDeleteTarget(t.id)}
                                            >
                                                <Trash2 className="h-3 w-3" />
                                            </Button>
                                        </div>
                                    </div>

                                    {editingCapId === t.id ? (
                                        <div className="flex items-center gap-2">
                                            <Input
                                                type="number"
                                                step="0.01"
                                                className="h-7 text-xs font-mono w-28"
                                                value={capValue}
                                                onChange={(e) => setCapValue(e.target.value)}
                                            />
                                            <Button size="sm" className="h-7 text-[10px]" onClick={() => handleSaveCap(t.id)} disabled={updateToken.isPending}>Save</Button>
                                            <Button variant="ghost" size="sm" className="h-7 text-[10px]" onClick={() => setEditingCapId(null)}>Cancel</Button>
                                        </div>
                                    ) : (
                                        <span className="text-[10px] text-muted-foreground font-mono">Plan cap: ${t.plan_cap_usd.toFixed(2)}</span>
                                    )}

                                    {credit && (
                                        <div className="space-y-1">
                                            <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
                                                <span>${credit.used_usd.toFixed(2)} / ${credit.cap_usd.toFixed(2)}</span>
                                                <span>{credit.pct.toFixed(0)}%</span>
                                            </div>
                                            <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                                                <div className={`h-full ${barColor}`} style={{ width: `${Math.min(credit.pct, 100)}%` }} />
                                            </div>
                                            <div className="text-[9px] text-muted-foreground font-mono">
                                                Cycle {new Date(credit.cycle_start).toLocaleDateString()} – {new Date(credit.cycle_end).toLocaleDateString()}
                                                {!credit.is_usable && <span className="text-red-500 ml-1">· not usable{credit.error ? `: ${credit.error}` : ""}</span>}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
                <DialogContent className="max-w-sm">
                    <DialogHeader>
                        <DialogTitle className="text-sm">Remove this Apify token?</DialogTitle>
                        <DialogDescription className="text-xs">
                            Runs scheduled with this token will fall back to another usable token, or be skipped if none remain.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>Cancel</Button>
                        <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => deleteTarget !== null && handleDelete(deleteTarget)}
                            disabled={deleteToken.isPending}
                        >
                            {deleteToken.isPending ? "Removing..." : "Remove Token"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

export default function SettingsPage() {
    const { theme } = useTheme();
    const isDark = theme === "dark";
    const { data: status, isLoading: isLoadingStatus } = useVaultStatus();
    const updateLLM = useUpdateLLMConfig();
    const { data: auditLogs, isLoading: isLoadingAudit } = useAuditLogs();
    const killSwitch = useKillSwitch();

    const [editingProvider, setEditingProvider] = useState<string | null>(null);
    const [editingModel, setEditingModel] = useState(false);
    const [killSwitchDialogOpen, setKillSwitchDialogOpen] = useState(false);

    const [apiKey, setApiKey] = useState("");
    const [modelName, setModelName] = useState("");
    const [customBaseUrl, setCustomBaseUrl] = useState("");

    useEffect(() => {
        if (status?.current_model) {
            setModelName(status.current_model);
        }
        if (status?.custom_base_url) {
            setCustomBaseUrl(status.custom_base_url);
        }
    }, [status]);

    const handleSaveLLM = async (provider: LLMProvider) => {
        if (provider !== "ollama" && provider !== "custom" && !apiKey) {
            toast.error("API key is required");
            return;
        }
        if ((provider === "ollama" || provider === "custom") && !customBaseUrl) {
            toast.error("A base URL is required for this provider");
            return;
        }

        try {
            await updateLLM.mutateAsync({
                provider,
                api_key: apiKey || undefined,
                custom_base_url: (provider === "ollama" || provider === "custom") ? customBaseUrl : undefined,
            });
            toast.success(`${provider} configuration updated`);
            setEditingProvider(null);
            setApiKey("");
        } catch (err: any) {
            toast.error(err.response?.data?.detail || err.message || "Failed to save key");
        }
    };

    const handleUpdateModel = async () => {
        if (!modelName) {
            toast.error("Model name is required");
            return;
        }

        try {
            await updateLLM.mutateAsync({
                provider: (status?.current_provider as LLMProvider) || "openrouter",
                model_name: modelName,
            });
            toast.success("Active model updated");
            setEditingModel(false);
        } catch (err: any) {
            toast.error(err.response?.data?.detail || err.message || "Failed to update model");
        }
    };

    const handleKillSwitch = async () => {
        try {
            await killSwitch.mutateAsync();
            toast.success("Kill switch activated — all campaigns paused.");
            setKillSwitchDialogOpen(false);
        } catch (err: any) {
            toast.error(err.response?.data?.detail || err.message || "Failed to activate kill switch");
        }
    };

    if (isLoadingStatus) {
        return (
            <div className="flex h-[calc(100vh-200px)] items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-8 p-8 max-w-6xl mx-auto">
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 text-foreground">
                    <Settings className="h-5 w-5 text-primary" />
                    <h1 className="text-xl font-semibold tracking-tight">Organization Settings</h1>
                </div>
                <p className="text-sm text-muted-foreground">
                    Configure your AI engine, Apify vault, team, and platform-wide guardrails.
                </p>
            </div>

            <Tabs defaultValue="platform" className="w-full">
                <TabsList className="bg-muted/50 p-1 mb-8 flex-wrap h-auto">
                    <TabsTrigger value="platform" className="gap-2">
                        <Zap className="h-3.5 w-3.5" />
                        Platform & LLM
                    </TabsTrigger>
                    <TabsTrigger value="apify" className="gap-2">
                        <Database className="h-3.5 w-3.5" />
                        Apify Keys
                    </TabsTrigger>
                    <TabsTrigger value="team" className="gap-2">
                        <Users className="h-3.5 w-3.5" />
                        Team
                    </TabsTrigger>
                    <TabsTrigger value="usage" className="gap-2">
                        <CreditCard className="h-3.5 w-3.5" />
                        Usage
                    </TabsTrigger>
                    <TabsTrigger value="audit" className="gap-2">
                        <History className="h-3.5 w-3.5" />
                        Audit Logs
                    </TabsTrigger>
                    <TabsTrigger value="danger" className="gap-2">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        Danger Zone
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="platform" className="outline-none">
                    <div className="max-w-2xl flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6 shadow-none">
                        <div className="flex items-center gap-2 mb-2">
                            <Key className="h-4 w-4 text-muted-foreground" />
                            <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">LLM Providers</h2>
                        </div>

                        <div className="flex flex-col gap-4 bg-primary/5 p-4 rounded-md border border-primary/10">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <Bot className="h-4 w-4 text-primary" />
                                    <span className="text-sm font-medium">Active Deployment Model</span>
                                </div>
                                {!editingModel && (
                                    <Button variant="link" size="sm" className="h-auto p-0 text-[10px] uppercase font-mono" onClick={() => setEditingModel(true)}>
                                        Change
                                    </Button>
                                )}
                            </div>

                            {editingModel ? (
                                <div className="flex gap-2">
                                    <Input
                                        className="h-8 text-xs font-mono"
                                        value={modelName}
                                        onChange={(e) => setModelName(e.target.value)}
                                        placeholder="openrouter/anthropic/claude-3.5-sonnet"
                                    />
                                    <Button size="sm" className="h-8 text-[10px] uppercase font-mono" onClick={handleUpdateModel} disabled={updateLLM.isPending}>
                                        Apply
                                    </Button>
                                    <Button variant="ghost" size="sm" className="h-8 text-[10px] uppercase font-mono" onClick={() => setEditingModel(false)}>
                                        Cancel
                                    </Button>
                                </div>
                            ) : (
                                <div className="flex items-center gap-2">
                                    <Badge variant="secondary" className="font-mono text-xs py-1">
                                        {status?.current_model || "Not Configured"}
                                    </Badge>
                                    <span className="text-[10px] text-muted-foreground lowercase">via {status?.current_provider || "openrouter (default)"}</span>
                                </div>
                            )}
                        </div>

                        <Separator className="bg-border/40 my-2" />

                        <div className="flex flex-col gap-5">
                            {PROVIDERS.map((provider) => {
                                const isActive = status?.current_provider === provider.id;
                                const isEditing = editingProvider === provider.id;
                                const needsBaseUrl = provider.id === "ollama" || provider.id === "custom";

                                return (
                                    <div key={provider.id} className="flex flex-col gap-3">
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-medium">{provider.name}</span>
                                                {provider.isDefault && (
                                                    <Badge variant="outline" className="text-[9px] uppercase font-mono py-0 h-4 border-primary/30 text-primary">Default</Badge>
                                                )}
                                                {isActive && !isEditing && (
                                                    <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] uppercase font-mono py-0 h-4">Active</Badge>
                                                )}
                                            </div>
                                            {!isEditing && (
                                                <Button variant="outline" size="sm" className="h-7 text-[10px] uppercase font-mono px-2" onClick={() => { setEditingProvider(provider.id); setApiKey(""); }}>
                                                    {isActive ? "Update" : "Use this"}
                                                </Button>
                                            )}
                                        </div>
                                        {isEditing && (
                                            <div className="flex flex-col gap-1.5 pl-2 border-l-2 border-primary/20 bg-muted/5 p-3 rounded-r-md">
                                                {!needsBaseUrl && (
                                                    <Input type="password" placeholder={provider.placeholder} className="h-8 text-sm font-mono shadow-none border-border/40" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                                                )}
                                                {needsBaseUrl && (
                                                    <>
                                                        <Input placeholder="https://your-host:11434/v1" className="h-8 text-sm font-mono shadow-none border-border/40" value={customBaseUrl} onChange={(e) => setCustomBaseUrl(e.target.value)} />
                                                        <Input type="password" placeholder="API key (optional)" className="h-8 text-sm font-mono shadow-none border-border/40" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                                                    </>
                                                )}
                                                <div className="flex justify-between items-center mt-1">
                                                    <p className="text-[10px] text-muted-foreground italic">Try: {provider.hint}</p>
                                                    <div className="flex gap-2">
                                                        <Button size="sm" className="h-7 px-3 text-[10px] uppercase font-mono" onClick={() => handleSaveLLM(provider.id)} disabled={updateLLM.isPending}>Save</Button>
                                                        <Button variant="ghost" size="sm" className="h-7 px-3 text-[10px] uppercase font-mono" onClick={() => setEditingProvider(null)}>Cancel</Button>
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </TabsContent>

                <TabsContent value="apify" className="outline-none">
                    <ApifyKeysTab />
                </TabsContent>

                <TabsContent value="team" className="outline-none border border-border/40 rounded-md overflow-hidden bg-background min-h-[600px]">
                    <OrganizationProfile
                        appearance={{
                            baseTheme: isDark ? dark : undefined,
                            variables: {
                                colorPrimary: isDark ? '#fafafa' : '#09090b',
                                colorBackground: isDark ? '#09090b' : '#ffffff',
                                colorText: isDark ? '#fafafa' : '#09090b',
                            },
                        }}
                        routing="hash"
                    />
                </TabsContent>

                <TabsContent value="usage" className="outline-none">
                    <div className="flex flex-col items-center justify-center py-20 border border-dashed border-border/60 rounded-md bg-muted/5">
                        <CreditCard className="h-8 w-8 text-muted-foreground mb-4 opacity-20" />
                        <p className="text-sm font-medium text-muted-foreground">See the Overview page for live usage meters</p>
                        <p className="text-[11px] text-muted-foreground/60 uppercase tracking-widest mt-1">Detailed billing UI is a later milestone</p>
                    </div>
                </TabsContent>

                <TabsContent value="audit" className="outline-none">
                    {isLoadingAudit ? (
                        <div className="flex justify-center py-20">
                            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                        </div>
                    ) : !auditLogs || auditLogs.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-20 border border-dashed border-border/60 rounded-md bg-muted/5">
                            <History className="h-8 w-8 text-muted-foreground mb-4 opacity-20" />
                            <p className="text-sm font-medium text-muted-foreground">No audit log entries yet</p>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {auditLogs.map((entry) => (
                                <div key={entry.id} className="flex items-center justify-between border border-border/40 rounded-md px-4 py-2.5 bg-muted/5">
                                    <div className="flex items-center gap-3">
                                        <Badge variant="outline" className="text-[9px] font-mono py-0 h-4">{entry.action}</Badge>
                                        {entry.details && (
                                            <span className="text-[11px] text-muted-foreground font-mono truncate max-w-[400px]">
                                                {JSON.stringify(entry.details)}
                                            </span>
                                        )}
                                    </div>
                                    <span className="text-[10px] text-muted-foreground font-mono shrink-0">{new Date(entry.timestamp).toLocaleString()}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </TabsContent>

                <TabsContent value="danger" className="outline-none">
                    <div className="border border-destructive/20 bg-destructive/5 rounded-md p-6">
                        <div className="flex flex-col gap-1 mb-6">
                            <h3 className="text-sm font-semibold text-destructive uppercase tracking-wider">The "Red" Button</h3>
                            <p className="text-sm text-muted-foreground">
                                Kill switch pauses every active campaign for this org and revokes queued pipeline tasks.
                                It never deletes or unposts anything — Sentinel never posted anything itself. Audit-logged.
                            </p>
                        </div>
                        <Button variant="destructive" className="gap-2 uppercase font-bold tracking-tighter" onClick={() => setKillSwitchDialogOpen(true)}>
                            <AlertTriangle className="h-4 w-4" />
                            Activate Kill Switch
                        </Button>
                    </div>

                    <Dialog open={killSwitchDialogOpen} onOpenChange={setKillSwitchDialogOpen}>
                        <DialogContent className="max-w-md">
                            <DialogHeader>
                                <DialogTitle className="flex items-center gap-2 text-sm">
                                    <ShieldAlert className="h-4 w-4 text-destructive" />
                                    Activate Kill Switch?
                                </DialogTitle>
                                <DialogDescription className="text-xs">
                                    Every ACTIVE campaign in this org will be paused immediately. No new drafts will be
                                    generated until you manually resume campaigns. This is logged to the audit trail.
                                </DialogDescription>
                            </DialogHeader>
                            <DialogFooter>
                                <Button variant="ghost" size="sm" onClick={() => setKillSwitchDialogOpen(false)}>Cancel</Button>
                                <Button variant="destructive" size="sm" onClick={handleKillSwitch} disabled={killSwitch.isPending}>
                                    {killSwitch.isPending ? "Activating..." : "Yes, pause everything"}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                </TabsContent>
            </Tabs>
        </div>
    );
}

"use client";

import { useState, useEffect } from "react";
import {
    ShieldCheck,
    Key,
    Bot,
    CheckCircle2,
    Loader2,
    RefreshCcw,
    Settings,
    Users,
    CreditCard,
    History,
    AlertTriangle,
    Zap
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
    useVaultStatus,
    useUpdateLLMConfig,
    useSaveRedditCreds
} from "@/hooks/use-vaults";

const PROVIDERS = [
    { id: "openai", name: "OpenAI", placeholder: "sk-...", hint: "gpt-4o, gpt-4-turbo" },
    { id: "anthropic", name: "Anthropic", placeholder: "sk-ant-...", hint: "claude-3-5-sonnet-20241022" },
    { id: "gemini", name: "Google Gemini", placeholder: "AIza...", hint: "gemini/gemini-1.5-pro" },
    { id: "openrouter", name: "OpenRouter", placeholder: "sk-or-...", hint: "openrouter/anthropic/claude-3.5-sonnet" },
] as const;

export default function SettingsPage() {
    const { theme } = useTheme();
    const isDark = theme === "dark";
    const { data: status, isLoading: isLoadingStatus } = useVaultStatus();
    const updateLLM = useUpdateLLMConfig();
    const saveReddit = useSaveRedditCreds();

    // UI State
    const [editingProvider, setEditingProvider] = useState<string | null>(null);
    const [editingModel, setEditingModel] = useState(false);
    const [editingReddit, setEditingReddit] = useState(false);

    // Form States
    const [apiKey, setApiKey] = useState("");
    const [modelName, setModelName] = useState("");

    const [redditClientId, setRedditClientId] = useState("");
    const [redditClientSecret, setRedditClientSecret] = useState("");
    const [redditUsername, setRedditUsername] = useState("");
    const [redditPassword, setRedditPassword] = useState("");

    // Initialize model name from status
    useEffect(() => {
        if (status?.current_model) {
            setModelName(status.current_model);
        }
    }, [status]);

    const handleSaveLLM = async (provider: string) => {
        if (!apiKey) {
            toast.error("API key is required");
            return;
        }

        try {
            await updateLLM.mutateAsync({
                provider: provider as any,
                api_key: apiKey
            });
            toast.success(`${provider} configuration updated`);
            setEditingProvider(null);
            setApiKey("");
        } catch (err: any) {
            toast.error(err.message || "Failed to save key");
        }
    };

    const handleUpdateModel = async () => {
        if (!modelName) {
            toast.error("Model name is required");
            return;
        }

        if (!modelName.includes("/")) {
            toast.error("Invalid format. Use 'provider/model' (e.g., gemini/gemini-1.5-pro)");
            return;
        }

        try {
            await updateLLM.mutateAsync({
                provider: (status?.current_provider as any) || "openai",
                model_name: modelName
            });
            toast.success("Active model updated");
            setEditingModel(false);
        } catch (err: any) {
            toast.error(err.message || "Failed to update model");
        }
    };

    const handleSaveReddit = async () => {
        if (!redditClientId || !redditClientSecret || !redditUsername || !redditPassword) {
            toast.error("All Reddit credentials are required");
            return;
        }

        try {
            await saveReddit.mutateAsync({
                client_id: redditClientId,
                client_secret: redditClientSecret,
                username: redditUsername,
                password: redditPassword,
            });
            toast.success("Reddit credentials saved");
            setEditingReddit(false);
            setRedditClientId("");
            setRedditClientSecret("");
            setRedditUsername("");
            setRedditPassword("");
        } catch (err: any) {
            toast.error(err.message || "Failed to save Reddit credentials");
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
            {/* Header */}
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 text-foreground">
                    <Settings className="h-5 w-5 text-primary" />
                    <h1 className="text-xl font-semibold tracking-tight">Organization Settings</h1>
                </div>
                <p className="text-sm text-muted-foreground">
                    Configure your AI engine, manage your team, and monitor platform usage.
                </p>
            </div>

            <Tabs defaultValue="platform" className="w-full">
                <TabsList className="bg-muted/50 p-1 mb-8">
                    <TabsTrigger value="platform" className="gap-2">
                        <Zap className="h-3.5 w-3.5" />
                        Platform & LLM
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
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        {/* LLM Providers */}
                        <div className="flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6 shadow-none">
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
                                            placeholder="provider/model-name"
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
                                        <span className="text-[10px] text-muted-foreground lowercase">via {status?.current_provider || "N/A"}</span>
                                    </div>
                                )}
                            </div>

                            <Separator className="bg-border/40 my-2" />

                            <div className="flex flex-col gap-5">
                                {PROVIDERS.map((provider) => {
                                    const isConnected = status?.[`${provider.id}_connected` as keyof typeof status];
                                    const isEditing = editingProvider === provider.id;

                                    return (
                                        <div key={provider.id} className="flex flex-col gap-3">
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-sm font-medium">{provider.name}</span>
                                                    {isConnected && !isEditing && (
                                                        <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] uppercase font-mono py-0 h-4">Connected</Badge>
                                                    )}
                                                </div>
                                                {isConnected && !isEditing && (
                                                    <Button variant="outline" size="sm" className="h-7 text-[10px] uppercase font-mono px-2" onClick={() => { setEditingProvider(provider.id); setApiKey(""); }}>
                                                        Update
                                                    </Button>
                                                )}
                                            </div>
                                            {(isEditing || !isConnected) && (
                                                <div className="flex flex-col gap-1.5 pl-2 border-l-2 border-primary/20 bg-muted/5 p-3 rounded-r-md">
                                                    <Input type="password" placeholder={provider.placeholder} className="h-8 text-sm font-mono shadow-none border-border/40" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                                                    <div className="flex justify-between items-center mt-1">
                                                        <p className="text-[10px] text-muted-foreground italic">Try: {provider.hint}</p>
                                                        <div className="flex gap-2">
                                                            <Button size="sm" className="h-7 px-3 text-[10px] uppercase font-mono" onClick={() => handleSaveLLM(provider.id)} disabled={updateLLM.isPending}>Save</Button>
                                                            {isEditing && <Button variant="ghost" size="sm" className="h-7 px-3 text-[10px] uppercase font-mono" onClick={() => setEditingProvider(null)}>Cancel</Button>}
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>

                        {/* Reddit PRAW Vault */}
                        <div className="flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6 shadow-none self-start">
                            <div className="flex items-center gap-2 mb-2">
                                <Bot className="h-4 w-4 text-muted-foreground" />
                                <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Reddit PRAW Vault</h2>
                            </div>

                            <div className="flex flex-col gap-4">
                                <div className="flex items-center justify-between">
                                    <div className="flex flex-col gap-0.5">
                                        <span className="text-sm font-medium">Connected Bot</span>
                                        {status?.reddit_username && !editingReddit && (
                                            <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] font-mono py-0 h-4 lowercase">u/{status.reddit_username}</Badge>
                                        )}
                                    </div>
                                    {status?.reddit_username && !editingReddit && (
                                        <Button variant="outline" size="sm" className="h-7 text-[10px] uppercase font-mono px-2" onClick={() => setEditingReddit(true)}>Update</Button>
                                    )}
                                </div>

                                {(!status?.reddit_username || editingReddit) && (
                                    <div className="grid grid-cols-1 gap-4 mt-2 bg-muted/5 p-4 rounded-md border border-border/40">
                                        <div className="grid grid-cols-2 gap-3">
                                            <Input placeholder="Client ID" className="h-8 text-xs font-mono shadow-none border-border/40" value={redditClientId} onChange={(e) => setRedditClientId(e.target.value)} />
                                            <Input type="password" placeholder="Client Secret" className="h-8 text-xs font-mono shadow-none border-border/40" value={redditClientSecret} onChange={(e) => setRedditClientSecret(e.target.value)} />
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <Input placeholder="Username" className="h-8 text-xs font-mono shadow-none border-border/40" value={redditUsername} onChange={(e) => setRedditUsername(e.target.value)} />
                                            <Input type="password" placeholder="Password" className="h-8 text-xs font-mono shadow-none border-border/40" value={redditPassword} onChange={(e) => setRedditPassword(e.target.value)} />
                                        </div>
                                        <div className="flex gap-2 mt-2">
                                            <Button className="flex-1 h-8 text-[10px] uppercase font-mono" onClick={handleSaveReddit} disabled={saveReddit.isPending}>Save Credentials</Button>
                                            {editingReddit && <Button variant="ghost" className="h-8 text-[10px] uppercase font-mono px-4" onClick={() => setEditingReddit(false)}>Cancel</Button>}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
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
                        routing="hash" // Standard for embedded in dashboard
                    />
                </TabsContent>

                <TabsContent value="usage" className="outline-none">
                    <div className="flex flex-col items-center justify-center py-20 border border-dashed border-border/60 rounded-md bg-muted/5">
                        <CreditCard className="h-8 w-8 text-muted-foreground mb-4 opacity-20" />
                        <p className="text-sm font-medium text-muted-foreground">Usage & Billing charts coming soon</p>
                        <p className="text-[11px] text-muted-foreground/60 uppercase tracking-widest mt-1">Pending API Implementation</p>
                    </div>
                </TabsContent>

                <TabsContent value="audit" className="outline-none">
                    <div className="flex flex-col items-center justify-center py-20 border border-dashed border-border/60 rounded-md bg-muted/5">
                        <History className="h-8 w-8 text-muted-foreground mb-4 opacity-20" />
                        <p className="text-sm font-medium text-muted-foreground">Audit Log history coming soon</p>
                        <p className="text-[11px] text-muted-foreground/60 uppercase tracking-widest mt-1">Pending API Implementation</p>
                    </div>
                </TabsContent>

                <TabsContent value="danger" className="outline-none">
                    <div className="border border-destructive/20 bg-destructive/5 rounded-md p-6">
                        <div className="flex flex-col gap-1 mb-6">
                            <h3 className="text-sm font-semibold text-destructive uppercase tracking-wider">The "Red" Button</h3>
                            <p className="text-sm text-muted-foreground">
                                Use the Kill Switch to immediately halt all campaign scraping and draft generation.
                                This is a platform-wide emergency stop.
                            </p>
                        </div>
                        <Button variant="destructive" className="gap-2 uppercase font-bold tracking-tighter">
                            <AlertTriangle className="h-4 w-4" />
                            Activate Global Kill Switch
                        </Button>
                    </div>
                </TabsContent>
            </Tabs>
        </div>
    );
}

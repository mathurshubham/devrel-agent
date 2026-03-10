"use client";

import { useState, useEffect } from "react";
import {
    ShieldCheck,
    Key,
    Bot,
    CheckCircle2,
    Loader2,
    RefreshCcw,
    Settings
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
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

export default function VaultsPage() {
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

        // Regex validation for LiteLLM format: provider/model
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
                    <ShieldCheck className="h-5 w-5 text-primary" />
                    <h1 className="text-xl font-semibold tracking-tight">Security & Vaults</h1>
                </div>
                <p className="text-sm text-muted-foreground">
                    Manage your API keys and Reddit bot credentials. Secrets are symmetrically encrypted at rest.
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Section A: LLM Providers */}
                <div className="flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6 shadow-none">
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                            <Key className="h-4 w-4 text-muted-foreground" />
                            <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">LLM Providers</h2>
                        </div>
                    </div>

                    <Separator className="bg-border/40" />

                    {/* Active Model Selection (Step 6 Implementation) */}
                    <div className="flex flex-col gap-4 bg-primary/5 p-4 rounded-md border border-primary/10">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <Settings className="h-4 w-4 text-primary" />
                                <span className="text-sm font-medium">Global Active Model</span>
                            </div>
                            {!editingModel && (
                                <Button
                                    variant="link"
                                    size="sm"
                                    className="h-auto p-0 text-[10px] uppercase font-mono"
                                    onClick={() => setEditingModel(true)}
                                >
                                    Change Model
                                </Button>
                            )}
                        </div>

                        {editingModel ? (
                            <div className="flex flex-col gap-2">
                                <p className="text-[10px] text-muted-foreground italic mb-1">
                                    LiteLLM format required. Examples: <code>gemini/gemini-1.5-pro</code>, <code>openrouter/anthropic/claude-3.5-sonnet</code>
                                </p>
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
                            </div>
                        ) : (
                            <div className="flex items-center gap-2">
                                <Badge variant="secondary" className="font-mono text-xs py-1">
                                    {status?.current_model || "Not Configured"}
                                </Badge>
                                <span className="text-[10px] text-muted-foreground lowercase">
                                    via {status?.current_provider || "N/A"}
                                </span>
                            </div>
                        )}
                    </div>

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
                                                <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] uppercase font-mono py-0 h-4">
                                                    Connected
                                                </Badge>
                                            )}
                                        </div>
                                        {isConnected && !isEditing && (
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                className="h-7 text-[10px] uppercase font-mono px-2"
                                                onClick={() => {
                                                    setEditingProvider(provider.id);
                                                    setApiKey("");
                                                }}
                                            >
                                                <RefreshCcw className="mr-1 h-3 w-3" />
                                                Update
                                            </Button>
                                        )}
                                    </div>

                                    {(isEditing || !isConnected) && (
                                        <div className="flex flex-col gap-1.5 pl-2 border-l-2 border-primary/20 bg-muted/5 p-3 rounded-r-md">
                                            <label className="text-[10px] font-mono uppercase text-muted-foreground">
                                                API Key
                                            </label>
                                            <div className="flex gap-2">
                                                <Input
                                                    type="password"
                                                    placeholder={provider.placeholder}
                                                    className="h-8 text-sm font-mono shadow-none border-border/40"
                                                    value={apiKey}
                                                    onChange={(e) => setApiKey(e.target.value)}
                                                />
                                                <Button
                                                    size="sm"
                                                    className="h-8 px-3 text-[10px] uppercase font-mono"
                                                    onClick={() => handleSaveLLM(provider.id)}
                                                    disabled={updateLLM.isPending}
                                                >
                                                    {updateLLM.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                                                </Button>
                                                {isEditing && (
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="h-8 px-3 text-[10px] uppercase font-mono"
                                                        onClick={() => setEditingProvider(null)}
                                                    >
                                                        Cancel
                                                    </Button>
                                                )}
                                            </div>
                                            <p className="text-[10px] text-muted-foreground mt-1">
                                                Safe fallback: {provider.hint}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Section B: Reddit Credentials */}
                <div className="flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6 shadow-none self-start">
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                            <Bot className="h-4 w-4 text-muted-foreground" />
                            <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">PRAW Vault</h2>
                        </div>
                    </div>

                    <Separator className="bg-border/40" />

                    <div className="flex flex-col gap-4">
                        <div className="flex items-center justify-between">
                            <div className="flex flex-col gap-0.5">
                                <span className="text-sm font-medium">Reddit Account</span>
                                {status?.reddit_username && !editingReddit && (
                                    <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] font-mono py-0 h-4 lowercase">
                                        Connected as u/{status.reddit_username}
                                    </Badge>
                                )}
                            </div>
                            {status?.reddit_username && !editingReddit ? (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 text-[10px] uppercase font-mono px-2"
                                    onClick={() => setEditingReddit(true)}
                                >
                                    <RefreshCcw className="mr-1 h-3 w-3" />
                                    Update
                                </Button>
                            ) : null}
                        </div>

                        {(!status?.reddit_username || editingReddit) && (
                            <div className="grid grid-cols-1 gap-4 mt-2 bg-muted/5 p-4 rounded-md border border-border/40">
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="flex flex-col gap-1.5">
                                        <label className="text-[10px] font-mono uppercase text-muted-foreground">
                                            Client ID
                                        </label>
                                        <Input
                                            placeholder="ID"
                                            className="h-8 text-xs font-mono shadow-none border-border/40"
                                            value={redditClientId}
                                            onChange={(e) => setRedditClientId(e.target.value)}
                                        />
                                    </div>
                                    <div className="flex flex-col gap-1.5">
                                        <label className="text-[10px] font-mono uppercase text-muted-foreground">
                                            Client Secret
                                        </label>
                                        <Input
                                            type="password"
                                            placeholder="Secret"
                                            className="h-8 text-xs font-mono shadow-none border-border/40"
                                            value={redditClientSecret}
                                            onChange={(e) => setRedditClientSecret(e.target.value)}
                                        />
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div className="flex flex-col gap-1.5">
                                        <label className="text-[10px] font-mono uppercase text-muted-foreground">
                                            Username
                                        </label>
                                        <Input
                                            placeholder="u/..."
                                            className="h-8 text-xs font-mono shadow-none border-border/40"
                                            value={redditUsername}
                                            onChange={(e) => setRedditUsername(e.target.value)}
                                        />
                                    </div>
                                    <div className="flex flex-col gap-1.5">
                                        <label className="text-[10px] font-mono uppercase text-muted-foreground">
                                            Password
                                        </label>
                                        <Input
                                            type="password"
                                            placeholder="Password"
                                            className="h-8 text-xs font-mono shadow-none border-border/40"
                                            value={redditPassword}
                                            onChange={(e) => setRedditPassword(e.target.value)}
                                        />
                                    </div>
                                </div>

                                <div className="flex gap-2 mt-2">
                                    <Button
                                        className="flex-1 h-8 text-[10px] uppercase font-mono"
                                        onClick={handleSaveReddit}
                                        disabled={saveReddit.isPending}
                                    >
                                        {saveReddit.isPending ? <Loader2 className="h-3 w-3 animate-spin mr-2" /> : <CheckCircle2 className="h-3 w-3 mr-2" />}
                                        Save Credentials
                                    </Button>
                                    {editingReddit && (
                                        <Button
                                            variant="ghost"
                                            className="h-8 text-[10px] uppercase font-mono px-4"
                                            onClick={() => {
                                                setEditingReddit(false);
                                                setRedditClientId("");
                                                setRedditClientSecret("");
                                                setRedditUsername("");
                                                setRedditPassword("");
                                            }}
                                        >
                                            Cancel
                                        </Button>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

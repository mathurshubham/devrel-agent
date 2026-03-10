"use client";

import { useState } from "react";
import {
    ShieldCheck,
    Key,
    Bot,
    CheckCircle2,
    Loader2,
    RefreshCcw,
    Plus
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
    useVaultStatus,
    useSaveLLMKey,
    useSaveRedditCreds
} from "@/hooks/use-vaults";

export default function VaultsPage() {
    const { data: status, isLoading: isLoadingStatus } = useVaultStatus();

    const [editingOpenAI, setEditingOpenAI] = useState(false);
    const [editingAnthropic, setEditingAnthropic] = useState(false);
    const [editingReddit, setEditingReddit] = useState(false);

    // Form states
    const [openaiKey, setOpenaiKey] = useState("");
    const [anthropicKey, setAnthropicKey] = useState("");

    const [redditClientId, setRedditClientId] = useState("");
    const [redditClientSecret, setRedditClientSecret] = useState("");
    const [redditUsername, setRedditUsername] = useState("");
    const [redditPassword, setRedditPassword] = useState("");

    const saveLLM = useSaveLLMKey();
    const saveReddit = useSaveRedditCreds();

    const handleSaveLLM = async (provider: "openai" | "anthropic") => {
        const api_key = provider === "openai" ? openaiKey : anthropicKey;
        if (!api_key) {
            toast.error("API key is required");
            return;
        }

        try {
            await saveLLM.mutateAsync({ provider, api_key });
            toast.success(`${provider === "openai" ? "OpenAI" : "Anthropic"} key saved`);
            if (provider === "openai") {
                setEditingOpenAI(false);
                setOpenaiKey("");
            } else {
                setEditingAnthropic(false);
                setAnthropicKey("");
            }
        } catch (err: any) {
            toast.error(err.message || "Failed to save key");
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

                    {/* OpenAI */}
                    <div className="flex flex-col gap-4">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-medium">OpenAI</span>
                                {status?.openai_connected && !editingOpenAI && (
                                    <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] uppercase font-mono py-0 h-4">
                                        Connected
                                    </Badge>
                                )}
                            </div>
                            {status?.openai_connected && !editingOpenAI ? (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 text-[10px] uppercase font-mono px-2"
                                    onClick={() => setEditingOpenAI(true)}
                                >
                                    <RefreshCcw className="mr-1 h-3 w-3" />
                                    Update Key
                                </Button>
                            ) : null}
                        </div>

                        {(!status?.openai_connected || editingOpenAI) && (
                            <div className="flex flex-col gap-3">
                                <div className="flex flex-col gap-1.5">
                                    <label htmlFor="openai-key" className="text-[10px] font-mono uppercase text-muted-foreground">
                                        API Key
                                    </label>
                                    <div className="flex gap-2">
                                        <Input
                                            id="openai-key"
                                            type="password"
                                            placeholder="sk-..."
                                            className="h-8 text-sm font-mono shadow-none border-border/40"
                                            value={openaiKey}
                                            onChange={(e) => setOpenaiKey(e.target.value)}
                                        />
                                        <Button
                                            size="sm"
                                            className="h-8 px-3 text-[10px] uppercase font-mono"
                                            onClick={() => handleSaveLLM("openai")}
                                            disabled={saveLLM.isPending}
                                        >
                                            {saveLLM.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                                        </Button>
                                        {editingOpenAI && (
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="h-8 px-3 text-[10px] uppercase font-mono"
                                                onClick={() => {
                                                    setEditingOpenAI(false);
                                                    setOpenaiKey("");
                                                }}
                                            >
                                                Cancel
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    <Separator className="bg-border/40" />

                    {/* Anthropic */}
                    <div className="flex flex-col gap-4">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-medium">Anthropic</span>
                                {status?.anthropic_connected && !editingAnthropic && (
                                    <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] uppercase font-mono py-0 h-4">
                                        Connected
                                    </Badge>
                                )}
                            </div>
                            {status?.anthropic_connected && !editingAnthropic ? (
                                <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 text-[10px] uppercase font-mono px-2"
                                    onClick={() => setEditingAnthropic(true)}
                                >
                                    <RefreshCcw className="mr-1 h-3 w-3" />
                                    Update Key
                                </Button>
                            ) : null}
                        </div>

                        {(!status?.anthropic_connected || editingAnthropic) && (
                            <div className="flex flex-col gap-3">
                                <div className="flex flex-col gap-1.5">
                                    <label htmlFor="anthropic-key" className="text-[10px] font-mono uppercase text-muted-foreground">
                                        API Key
                                    </label>
                                    <div className="flex gap-2">
                                        <Input
                                            id="anthropic-key"
                                            type="password"
                                            placeholder="sk-ant-..."
                                            className="h-8 text-sm font-mono shadow-none border-border/40"
                                            value={anthropicKey}
                                            onChange={(e) => setAnthropicKey(e.target.value)}
                                        />
                                        <Button
                                            size="sm"
                                            className="h-8 px-3 text-[10px] uppercase font-mono"
                                            onClick={() => handleSaveLLM("anthropic")}
                                            disabled={saveLLM.isPending}
                                        >
                                            {saveLLM.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                                        </Button>
                                        {editingAnthropic && (
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="h-8 px-3 text-[10px] uppercase font-mono"
                                                onClick={() => {
                                                    setEditingAnthropic(false);
                                                    setAnthropicKey("");
                                                }}
                                            >
                                                Cancel
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Section B: Reddit Credentials */}
                <div className="flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6 shadow-none">
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
                                    Update Credentials
                                </Button>
                            ) : null}
                        </div>

                        {(!status?.reddit_username || editingReddit) && (
                            <div className="grid grid-cols-1 gap-4 mt-2">
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

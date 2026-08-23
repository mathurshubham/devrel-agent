"use client";

import * as React from "react";
import { apiErrorText } from "@/hooks/use-api";
import { Plus, Trash2, Loader2, Users, Building2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
    useTargetAuthors,
    useAddTargetAuthor,
    useDeleteTargetAuthor,
    useCompetitors,
    useAddCompetitor,
    useDeleteCompetitor,
    type WatchlistTier,
    type CompetitorPlatform,
} from "@/hooks/use-analyst";

const COMPETITOR_PLATFORMS: CompetitorPlatform[] = ["REDDIT", "LINKEDIN", "TWITTER"];

function AuthorsPanel() {
    const { data: authors, isLoading } = useTargetAuthors();
    const addAuthor = useAddTargetAuthor();
    const deleteAuthor = useDeleteTargetAuthor();

    const [name, setName] = React.useState("");
    const [tier, setTier] = React.useState<WatchlistTier>(1);
    const [profileUrl, setProfileUrl] = React.useState("");

    const handleAdd = async () => {
        if (!name.trim() || !profileUrl.trim()) {
            toast.error("Name and profile URL are required");
            return;
        }
        try {
            await addAuthor.mutateAsync({ name: name.trim(), tier, profile_url: profileUrl.trim() });
            toast.success("Author added to watch list");
            setName("");
            setProfileUrl("");
            setTier(1);
        } catch (err: any) {
            toast.error(apiErrorText(err, "Failed to add author"));
        }
    };

    const handleDelete = async (id: number) => {
        try {
            await deleteAuthor.mutateAsync(id);
            toast.success("Author removed");
        } catch (err: any) {
            toast.error(apiErrorText(err, "Failed to remove author"));
        }
    };

    return (
        <div className="flex flex-col gap-4 border border-border/40 bg-muted/10 rounded-md p-6">
            <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Watch-list authors</h2>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
                Tier 1-3 names the Analyst triage step weighs when scoring relevance and signal tier.
            </p>

            <div className="flex flex-col gap-2">
                <Input
                    placeholder="Name"
                    className="h-9 text-sm"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                />
                <Input
                    placeholder="Profile URL"
                    className="h-9 text-sm font-mono"
                    value={profileUrl}
                    onChange={(e) => setProfileUrl(e.target.value)}
                />
                <div className="flex items-center gap-2">
                    <div className="flex rounded-md border border-border/40 overflow-hidden">
                        {([1, 2, 3] as WatchlistTier[]).map((t) => (
                            <button
                                key={t}
                                type="button"
                                onClick={() => setTier(t)}
                                className={`h-9 px-4 text-xs font-bold transition-colors ${
                                    tier === t ? "bg-primary/10 text-primary" : "bg-muted/20 text-muted-foreground hover:text-foreground"
                                }`}
                            >
                                Tier {t}
                            </button>
                        ))}
                    </div>
                    <Button size="sm" className="h-9 flex-1 text-[10px] uppercase font-mono" onClick={handleAdd} disabled={addAuthor.isPending}>
                        <Plus className="mr-1.5 h-3 w-3" />
                        {addAuthor.isPending ? "Adding..." : "Add Author"}
                    </Button>
                </div>
            </div>

            {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            ) : !authors || authors.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No watch-list authors yet.</p>
            ) : (
                <div className="flex flex-col gap-2">
                    {authors.map((author) => (
                        <div key={author.id} className="flex items-center justify-between rounded-md border border-border/40 bg-background p-2.5">
                            <div className="flex items-center gap-2 min-w-0">
                                <Badge variant="outline" className="text-[9px] font-mono py-0 h-4 shrink-0">T{author.tier ?? "-"}</Badge>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-sm font-medium truncate">{author.name}</span>
                                    {author.profile_url && (
                                        <a href={author.profile_url} target="_blank" rel="noreferrer" className="text-[10px] text-muted-foreground font-mono truncate hover:underline">
                                            {author.profile_url}
                                        </a>
                                    )}
                                </div>
                            </div>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500 shrink-0" onClick={() => handleDelete(author.id)}>
                                <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function CompetitorsPanel() {
    const { data: competitors, isLoading } = useCompetitors();
    const addCompetitor = useAddCompetitor();
    const deleteCompetitor = useDeleteCompetitor();

    const [platform, setPlatform] = React.useState<CompetitorPlatform>("REDDIT");
    const [name, setName] = React.useState("");
    const [url, setUrl] = React.useState("");

    const handleAdd = async () => {
        if (!name.trim() || !url.trim()) {
            toast.error("Name and URL are required");
            return;
        }
        try {
            await addCompetitor.mutateAsync({ platform, name: name.trim(), url: url.trim() });
            toast.success("Competitor added");
            setName("");
            setUrl("");
        } catch (err: any) {
            toast.error(apiErrorText(err, "Failed to add competitor"));
        }
    };

    const handleDelete = async (id: number) => {
        try {
            await deleteCompetitor.mutateAsync(id);
            toast.success("Competitor removed");
        } catch (err: any) {
            toast.error(apiErrorText(err, "Failed to remove competitor"));
        }
    };

    return (
        <div className="flex flex-col gap-4 border border-border/40 bg-muted/10 rounded-md p-6">
            <div className="flex items-center gap-2">
                <Building2 className="h-4 w-4 text-muted-foreground" />
                <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Competitors</h2>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
                Tracked alongside your own keywords so briefs surface competitor activity per pillar.
            </p>

            <div className="flex flex-col gap-2">
                <div className="grid grid-cols-3 gap-2">
                    {COMPETITOR_PLATFORMS.map((p) => (
                        <button
                            key={p}
                            type="button"
                            onClick={() => setPlatform(p)}
                            className={`h-9 rounded-md border text-xs font-bold transition-colors ${
                                platform === p ? "border-primary bg-primary/10 text-primary" : "border-border/40 bg-muted/20 text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            {p}
                        </button>
                    ))}
                </div>
                <Input
                    placeholder="Competitor name"
                    className="h-9 text-sm"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                />
                <div className="flex gap-2">
                    <Input
                        placeholder="Profile / company URL"
                        className="h-9 text-sm font-mono"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                    />
                    <Button size="sm" className="h-9 text-[10px] uppercase font-mono shrink-0" onClick={handleAdd} disabled={addCompetitor.isPending}>
                        <Plus className="mr-1.5 h-3 w-3" />
                        Add
                    </Button>
                </div>
            </div>

            {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            ) : !competitors || competitors.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">No competitors tracked yet.</p>
            ) : (
                <div className="flex flex-col gap-2">
                    {competitors.map((c) => (
                        <div key={c.id} className="flex items-center justify-between rounded-md border border-border/40 bg-background p-2.5">
                            <div className="flex items-center gap-2 min-w-0">
                                <Badge variant="outline" className="text-[9px] font-mono py-0 h-4 shrink-0">{c.platform ?? "—"}</Badge>
                                <div className="flex flex-col min-w-0">
                                    <span className="text-sm font-medium truncate">{c.name}</span>
                                    {c.url && (
                                        <a href={c.url} target="_blank" rel="noreferrer" className="text-[10px] text-muted-foreground font-mono truncate hover:underline">
                                            {c.url}
                                        </a>
                                    )}
                                </div>
                            </div>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500 shrink-0" onClick={() => handleDelete(c.id)}>
                                <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export function WatchlistPanel() {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <AuthorsPanel />
            <CompetitorsPanel />
        </div>
    );
}

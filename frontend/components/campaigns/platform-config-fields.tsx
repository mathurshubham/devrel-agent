"use client";

import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import type { Platform } from "@/hooks/use-campaigns";

export interface RedditConfig {
    sort: "top" | "new";
    time_filter: "day" | "week";
    max_posts_per_source: number;
    max_comments_per_post: number;
}

export interface LinkedInConfig {
    limit: number;
    sort_type: "date_posted" | "relevance";
    date_filter: string;
    exact_match: boolean;
}

export interface TwitterConfig {
    query_type: "Latest" | "Top";
    limit: number;
    lang: string;
    min_retweets: number;
    min_faves: number;
    min_replies: number;
}

export type PlatformConfig = RedditConfig | LinkedInConfig | TwitterConfig;

// Defaults per PRD §5.1 -- key names match backend/ingestion/inputs.py's
// platform_config reads exactly (max_posts_per_source, limit, etc.).
export const DEFAULT_PLATFORM_CONFIG: Record<Platform, PlatformConfig> = {
    REDDIT: { sort: "top", time_filter: "week", max_posts_per_source: 15, max_comments_per_post: 5 },
    LINKEDIN: { limit: 30, sort_type: "date_posted", date_filter: "any", exact_match: false },
    TWITTER: { query_type: "Latest", limit: 20, lang: "en", min_retweets: 0, min_faves: 0, min_replies: 0 },
};

function ToggleGroup<T extends string>({
    options,
    value,
    onChange,
}: {
    options: T[];
    value: T;
    onChange: (v: T) => void;
}) {
    return (
        <div className="flex rounded-md border border-border/40 overflow-hidden">
            {options.map((opt) => (
                <button
                    key={opt}
                    type="button"
                    onClick={() => onChange(opt)}
                    className={`h-8 flex-1 px-2 text-[11px] font-medium capitalize transition-colors ${
                        value === opt ? "bg-primary/10 text-primary" : "bg-muted/20 text-muted-foreground hover:text-foreground"
                    }`}
                >
                    {opt}
                </button>
            ))}
        </div>
    );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="space-y-1.5">
            <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">{label}</label>
            {children}
        </div>
    );
}

export function PlatformConfigFields({
    platform,
    config,
    onChange,
    disabled,
}: {
    platform: Platform;
    config: PlatformConfig;
    onChange: (config: PlatformConfig) => void;
    disabled?: boolean;
}) {
    if (platform === "REDDIT") {
        const c = config as RedditConfig;
        return (
            <div className="grid grid-cols-2 gap-4">
                <Field label="Sort">
                    <ToggleGroup options={["top", "new"]} value={c.sort} onChange={(v) => onChange({ ...c, sort: v })} />
                </Field>
                <Field label="Time filter">
                    <ToggleGroup options={["day", "week"]} value={c.time_filter} onChange={(v) => onChange({ ...c, time_filter: v })} />
                </Field>
                <Field label="Max posts / poll">
                    <Input
                        type="number"
                        min={1}
                        className="h-9 text-sm bg-muted/20 border-border/40"
                        value={c.max_posts_per_source}
                        disabled={disabled}
                        onChange={(e) => onChange({ ...c, max_posts_per_source: parseInt(e.target.value) || 0 })}
                    />
                </Field>
                <Field label="Max comments / post">
                    <Input
                        type="number"
                        min={0}
                        className="h-9 text-sm bg-muted/20 border-border/40"
                        value={c.max_comments_per_post}
                        disabled={disabled}
                        onChange={(e) => onChange({ ...c, max_comments_per_post: parseInt(e.target.value) || 0 })}
                    />
                </Field>
            </div>
        );
    }

    if (platform === "LINKEDIN") {
        const c = config as LinkedInConfig;
        return (
            <div className="grid grid-cols-2 gap-4">
                <Field label="Result limit">
                    <Input
                        type="number"
                        min={1}
                        className="h-9 text-sm bg-muted/20 border-border/40"
                        value={c.limit}
                        disabled={disabled}
                        onChange={(e) => onChange({ ...c, limit: parseInt(e.target.value) || 0 })}
                    />
                </Field>
                <Field label="Sort">
                    <ToggleGroup
                        options={["date_posted", "relevance"]}
                        value={c.sort_type}
                        onChange={(v) => onChange({ ...c, sort_type: v })}
                    />
                </Field>
                <Field label="Date filter">
                    <Input
                        placeholder="any / past-24h / past-week / past-month"
                        className="h-9 text-sm bg-muted/20 border-border/40"
                        value={c.date_filter}
                        disabled={disabled}
                        onChange={(e) => onChange({ ...c, date_filter: e.target.value })}
                    />
                </Field>
                <Field label="Exact match">
                    <div className="h-9 flex items-center gap-2">
                        <Checkbox
                            checked={c.exact_match}
                            disabled={disabled}
                            onCheckedChange={(checked) => onChange({ ...c, exact_match: !!checked })}
                        />
                        <span className="text-[11px] text-muted-foreground">Quote the value as an exact phrase</span>
                    </div>
                </Field>
            </div>
        );
    }

    const c = config as TwitterConfig;
    return (
        <div className="grid grid-cols-2 gap-4">
            <Field label="Query type">
                <ToggleGroup options={["Latest", "Top"]} value={c.query_type} onChange={(v) => onChange({ ...c, query_type: v })} />
            </Field>
            <Field label="Max items">
                <Input
                    type="number"
                    min={1}
                    className="h-9 text-sm bg-muted/20 border-border/40"
                    value={c.limit}
                    disabled={disabled}
                    onChange={(e) => onChange({ ...c, limit: parseInt(e.target.value) || 0 })}
                />
            </Field>
            <Field label="Language">
                <Input
                    placeholder="en"
                    className="h-9 text-sm bg-muted/20 border-border/40"
                    value={c.lang}
                    disabled={disabled}
                    onChange={(e) => onChange({ ...c, lang: e.target.value })}
                />
            </Field>
            <Field label="Min retweets">
                <Input
                    type="number"
                    min={0}
                    className="h-9 text-sm bg-muted/20 border-border/40"
                    value={c.min_retweets}
                    disabled={disabled}
                    onChange={(e) => onChange({ ...c, min_retweets: parseInt(e.target.value) || 0 })}
                />
            </Field>
            <Field label="Min likes">
                <Input
                    type="number"
                    min={0}
                    className="h-9 text-sm bg-muted/20 border-border/40"
                    value={c.min_faves}
                    disabled={disabled}
                    onChange={(e) => onChange({ ...c, min_faves: parseInt(e.target.value) || 0 })}
                />
            </Field>
            <Field label="Min replies">
                <Input
                    type="number"
                    min={0}
                    className="h-9 text-sm bg-muted/20 border-border/40"
                    value={c.min_replies}
                    disabled={disabled}
                    onChange={(e) => onChange({ ...c, min_replies: parseInt(e.target.value) || 0 })}
                />
            </Field>
        </div>
    );
}

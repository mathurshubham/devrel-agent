"use client";

import * as React from "react";
import { Loader2, MessageSquareQuote, Bot, Linkedin, Radar, ShieldAlert, Tags, DollarSign, X, Plus, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { useOrgSettings, useUpdateOrgSettings, type OrgSettings } from "@/hooks/use-org-settings";

const REPLY_HOOK_PRESETS: { id: string; label: string; text: string }[] = [
    { id: "banner", label: "Banner", text: "\n\n---\n*Disclosure: I work on the product this touches on.*" },
    { id: "soft", label: "Soft", text: "\n\n(disclosure: I'm involved with the product mentioned above)" },
    { id: "none", label: "None", text: "" },
];

type FormState = Pick<
    OrgSettings,
    | "reply_hook"
    | "scout_prompt"
    | "linkedin_stale_days"
    | "linkedin_stale_min_engagement"
    | "analyst_enabled"
    | "disclosure_reddit"
    | "pillar_taxonomy"
    | "apify_monthly_budget_usd"
>;

function toFormState(settings: OrgSettings): FormState {
    return {
        reply_hook: settings.reply_hook ?? "",
        scout_prompt: settings.scout_prompt ?? "",
        linkedin_stale_days: settings.linkedin_stale_days,
        linkedin_stale_min_engagement: settings.linkedin_stale_min_engagement,
        analyst_enabled: settings.analyst_enabled,
        disclosure_reddit: settings.disclosure_reddit,
        pillar_taxonomy: settings.pillar_taxonomy ?? [],
        apify_monthly_budget_usd: settings.apify_monthly_budget_usd,
    };
}

export function WorkspaceTab() {
    const { data: settings, isLoading } = useOrgSettings();
    const updateSettings = useUpdateOrgSettings();

    const [form, setForm] = React.useState<FormState | null>(null);
    const [newPillar, setNewPillar] = React.useState("");

    React.useEffect(() => {
        if (settings) {
            setForm(toFormState(settings));
        }
    }, [settings]);

    if (isLoading || !form) {
        return (
            <div className="flex justify-center py-20">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    const applyPreset = (text: string) => {
        setForm({ ...form, reply_hook: text });
    };

    const handleResetScoutPrompt = () => {
        setForm({ ...form, scout_prompt: "" });
    };

    const addPillar = () => {
        const trimmed = newPillar.trim();
        if (!trimmed) return;
        if (form.pillar_taxonomy.includes(trimmed)) {
            toast.error("That pillar already exists");
            return;
        }
        setForm({ ...form, pillar_taxonomy: [...form.pillar_taxonomy, trimmed] });
        setNewPillar("");
    };

    const removePillar = (pillar: string) => {
        setForm({ ...form, pillar_taxonomy: form.pillar_taxonomy.filter((p) => p !== pillar) });
    };

    const handleSave = async () => {
        try {
            await updateSettings.mutateAsync({
                reply_hook: form.reply_hook || null,
                scout_prompt: form.scout_prompt || null,
                linkedin_stale_days: form.linkedin_stale_days,
                linkedin_stale_min_engagement: form.linkedin_stale_min_engagement,
                analyst_enabled: form.analyst_enabled,
                disclosure_reddit: form.disclosure_reddit,
                pillar_taxonomy: form.pillar_taxonomy,
                apify_monthly_budget_usd: form.apify_monthly_budget_usd,
            });
            toast.success("Workspace settings saved");
        } catch (err: any) {
            toast.error(err?.response?.data?.detail || "Failed to save workspace settings");
        }
    };

    return (
        <div className="max-w-2xl flex flex-col gap-6 border border-border/40 bg-muted/10 rounded-md p-6">
            {/* Reply hook */}
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <MessageSquareQuote className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Reply hook</h2>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Appended idempotently to every finalized draft. Pick a preset to start from, or write your own.
                </p>
                <div className="flex gap-2">
                    {REPLY_HOOK_PRESETS.map((preset) => (
                        <Button
                            key={preset.id}
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 text-[10px] uppercase font-mono"
                            onClick={() => applyPreset(preset.text)}
                        >
                            {preset.label}
                        </Button>
                    ))}
                </div>
                <Textarea
                    placeholder="No reply hook configured"
                    className="min-h-[70px] text-sm shadow-none border-border/40"
                    value={form.reply_hook ?? ""}
                    onChange={(e) => setForm({ ...form, reply_hook: e.target.value })}
                />
            </div>

            <Separator className="bg-border/40" />

            {/* Scout prompt override */}
            <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Bot className="h-4 w-4 text-muted-foreground" />
                        <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Scout prompt override</h2>
                    </div>
                    <Button type="button" variant="ghost" size="sm" className="h-7 text-[10px] uppercase font-mono gap-1.5" onClick={handleResetScoutPrompt}>
                        <RotateCcw className="h-3 w-3" />
                        Reset to default
                    </Button>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Leave blank to use the system-seeded Scout prompt for each platform.
                </p>
                <Textarea
                    placeholder="System default scout prompt in use"
                    className="min-h-[120px] text-sm font-mono shadow-none border-border/40"
                    value={form.scout_prompt ?? ""}
                    onChange={(e) => setForm({ ...form, scout_prompt: e.target.value })}
                />
            </div>

            <Separator className="bg-border/40" />

            {/* LinkedIn stale filter */}
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <Linkedin className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">LinkedIn stale-post filter</h2>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Drops posts older than the given age AND below the given engagement. Leave either field blank to turn the filter off.
                </p>
                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">Stale after (days)</label>
                        <Input
                            type="number"
                            min={0}
                            placeholder="off"
                            className="h-9 text-sm shadow-none border-border/40"
                            value={form.linkedin_stale_days ?? ""}
                            onChange={(e) =>
                                setForm({ ...form, linkedin_stale_days: e.target.value === "" ? null : parseInt(e.target.value) })
                            }
                        />
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground block">Min. engagement</label>
                        <Input
                            type="number"
                            min={0}
                            placeholder="off"
                            className="h-9 text-sm shadow-none border-border/40"
                            value={form.linkedin_stale_min_engagement ?? ""}
                            onChange={(e) =>
                                setForm({
                                    ...form,
                                    linkedin_stale_min_engagement: e.target.value === "" ? null : parseInt(e.target.value),
                                })
                            }
                        />
                    </div>
                </div>
            </div>

            <Separator className="bg-border/40" />

            {/* Toggles */}
            <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between rounded-md border border-border/40 bg-background p-3">
                    <div className="flex items-center gap-2">
                        <Radar className="h-4 w-4 text-muted-foreground" />
                        <div className="flex flex-col">
                            <span className="text-sm font-medium">Weekly Analyst run</span>
                            <span className="text-[10px] text-muted-foreground">Beat-scheduled Mon 06:00 UTC when enabled.</span>
                        </div>
                    </div>
                    <Switch
                        checked={form.analyst_enabled}
                        onCheckedChange={(checked) => setForm({ ...form, analyst_enabled: checked })}
                    />
                </div>
                <div className="flex items-center justify-between rounded-md border border-border/40 bg-background p-3">
                    <div className="flex items-center gap-2">
                        <ShieldAlert className="h-4 w-4 text-muted-foreground" />
                        <div className="flex flex-col">
                            <span className="text-sm font-medium">Reddit disclosure line</span>
                            <span className="text-[10px] text-muted-foreground">Appends a disclosure when a draft references the product.</span>
                        </div>
                    </div>
                    <Switch
                        checked={form.disclosure_reddit}
                        onCheckedChange={(checked) => setForm({ ...form, disclosure_reddit: checked })}
                    />
                </div>
            </div>

            <Separator className="bg-border/40" />

            {/* Pillar taxonomy */}
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <Tags className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Pillar taxonomy</h2>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    Used by the Analyst's cluster step to tag each post with a primary/secondary pillar.
                </p>
                <div className="flex flex-wrap gap-2">
                    {form.pillar_taxonomy.length === 0 && (
                        <span className="text-xs text-muted-foreground italic">No pillars configured — the system default set will be used.</span>
                    )}
                    {form.pillar_taxonomy.map((pillar) => (
                        <Badge key={pillar} variant="outline" className="gap-1.5 py-1 px-2 text-xs">
                            {pillar}
                            <button type="button" onClick={() => removePillar(pillar)} className="text-muted-foreground hover:text-destructive">
                                <X className="h-3 w-3" />
                            </button>
                        </Badge>
                    ))}
                </div>
                <div className="flex gap-2">
                    <Input
                        placeholder="Add a pillar (e.g. Vector Search)"
                        className="h-9 text-sm shadow-none border-border/40"
                        value={newPillar}
                        onChange={(e) => setNewPillar(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                e.preventDefault();
                                addPillar();
                            }
                        }}
                    />
                    <Button type="button" size="sm" className="h-9 text-[10px] uppercase font-mono shrink-0" onClick={addPillar}>
                        <Plus className="mr-1.5 h-3 w-3" />
                        Add
                    </Button>
                </div>
            </div>

            <Separator className="bg-border/40" />

            {/* Apify budget */}
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <DollarSign className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">Apify monthly budget</h2>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    A run whose estimated cost plus month-to-date spend would exceed this is skipped before any actor starts.
                </p>
                <div className="flex items-center gap-2 max-w-[200px]">
                    <span className="text-muted-foreground font-mono">$</span>
                    <Input
                        type="number"
                        min={0}
                        step="0.01"
                        className="h-9 text-sm font-mono shadow-none border-border/40"
                        value={form.apify_monthly_budget_usd}
                        onChange={(e) => setForm({ ...form, apify_monthly_budget_usd: parseFloat(e.target.value) || 0 })}
                    />
                </div>
            </div>

            <div className="flex justify-end pt-2">
                <Button onClick={handleSave} disabled={updateSettings.isPending} className="h-9 text-xs font-bold uppercase tracking-wider px-6">
                    {updateSettings.isPending ? (
                        <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Saving...
                        </>
                    ) : (
                        "Save Workspace Settings"
                    )}
                </Button>
            </div>
        </div>
    );
}

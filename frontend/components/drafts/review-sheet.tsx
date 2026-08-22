"use client";

import * as React from "react";
import {
    ExternalLink,
    Info,
    MessageSquare,
    Zap,
    Copy,
    Check,
    BrainCircuit,
    ClipboardCheck,
    Undo2,
    Ban,
    XCircle,
} from "lucide-react";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
    PopoverHeader,
    PopoverTitle,
} from "@/components/ui/popover";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import {
    Draft,
    DraftStatus,
    useLockDraft,
    useUpdateDraft,
    useOpenCopyDraft,
    useConfirmPosted,
    useUnconfirmDraft,
    useRejectDraft,
    useIgnoreDraft,
    OpenCopyResponse,
} from "@/hooks/use-drafts";

interface ReviewSheetProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    draft: Draft;
}

const REJECT_REASONS = [
    { id: "off-tone", label: "Off-tone" },
    { id: "wrong-thread", label: "Wrong thread" },
    { id: "factual", label: "Factual issue" },
    { id: "other", label: "Other" },
];

const AUTOSAVE_DEBOUNCE_MS = 800;

export function ReviewSheet({ isOpen, onOpenChange, draft }: ReviewSheetProps) {
    const queryClient = useQueryClient();

    const [editedText, setEditedText] = React.useState(draft.ai_draft_text);
    const [savedText, setSavedText] = React.useState(draft.ai_draft_text);
    const [copyPayload, setCopyPayload] = React.useState<OpenCopyResponse | null>(null);
    const [localStatus, setLocalStatus] = React.useState<DraftStatus>(draft.status);
    const [copied, setCopied] = React.useState(false);
    const [liveUrl, setLiveUrl] = React.useState("");
    const [rejectReason, setRejectReason] = React.useState<string | null>(null);
    const [rejectNote, setRejectNote] = React.useState("");
    const [showReject, setShowReject] = React.useState(false);

    const { mutate: lock } = useLockDraft();
    const { mutate: updateDraft, isPending: isSaving } = useUpdateDraft();
    const { mutate: openCopy, isPending: isPreparingCopy } = useOpenCopyDraft();
    const { mutate: confirmPosted, isPending: isConfirming } = useConfirmPosted();
    const { mutate: unconfirm, isPending: isUnconfirming } = useUnconfirmDraft();
    const { mutate: rejectDraft, isPending: isRejecting } = useRejectDraft();
    const { mutate: ignoreDraft, isPending: isIgnoring } = useIgnoreDraft();

    const isBusy = isSaving || isConfirming || isUnconfirming || isRejecting || isIgnoring;
    const isDirty = editedText !== savedText;

    // Reset & lock + prefetch clipboard payload whenever a new draft is opened.
    React.useEffect(() => {
        if (!isOpen || !draft?.id) return;
        setEditedText(draft.ai_draft_text);
        setSavedText(draft.ai_draft_text);
        setLocalStatus(draft.status);
        setCopyPayload(null);
        setLiveUrl(draft.live_url || "");
        setShowReject(false);
        setRejectReason(null);
        setRejectNote("");

        lock(draft.id, {
            onError: (err: any) => toast.error(`Could not lock draft: ${err.message}`),
        });
        openCopy(draft.id, {
            onSuccess: (data) => setCopyPayload(data),
            onError: () => {
                // Non-fatal: user can still retry via the Open & Copy button.
            },
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [draft?.id, isOpen]);

    // Autosave the edited draft text, then refresh the cached clipboard
    // payload so the click handler always has fresh, already-fetched text.
    React.useEffect(() => {
        if (!isOpen || !isDirty) return;
        const timer = setTimeout(() => {
            updateDraft(
                { id: draft.id, ai_draft_text: editedText },
                {
                    onSuccess: () => {
                        setSavedText(editedText);
                        openCopy(draft.id, { onSuccess: (data) => setCopyPayload(data) });
                    },
                    onError: (err: any) => toast.error(`Autosave failed: ${err.message}`),
                }
            );
        }, AUTOSAVE_DEBOUNCE_MS);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editedText]);

    const copyReady = !!copyPayload && !isDirty && !isSaving && !isPreparingCopy;

    // This must stay synchronous: no awaits between the click and the two
    // browser calls, or Chrome/Safari silently drop the clipboard write.
    const handleOpenAndCopy = () => {
        if (isDirty) {
            toast.error("Saving your edits — try again in a moment.");
            return;
        }
        if (!copyPayload) {
            toast.error("Clipboard text isn't ready yet — try again in a moment.");
            openCopy(draft.id, { onSuccess: (data) => setCopyPayload(data) });
            return;
        }
        navigator.clipboard.writeText(copyPayload.clipboard_text);
        window.open(copyPayload.reply_target_url, "_blank", "noopener,noreferrer");
        setLocalStatus("AWAITING_CONFIRM");
        queryClient.invalidateQueries({ queryKey: ["drafts"] });
        toast.success("Copied to clipboard. Paste, submit, then confirm here.");
    };

    const handleCopyOnly = () => {
        if (!copyPayload) return;
        navigator.clipboard.writeText(copyPayload.clipboard_text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Draft copied to clipboard");
    };

    const handleConfirmPosted = () => {
        confirmPosted(
            { id: draft.id, live_url: liveUrl || undefined },
            {
                onSuccess: () => {
                    setLocalStatus("POSTED");
                    toast.success("Marked as posted!");
                    onOpenChange(false);
                },
                onError: (err: any) => toast.error(`Failed to confirm: ${err.message}`),
            }
        );
    };

    const handleDidntPost = () => {
        unconfirm(draft.id, {
            onSuccess: () => {
                setLocalStatus("PENDING");
                toast.message("Draft returned to Pending.");
            },
            onError: (err: any) => toast.error(`Failed: ${err.message}`),
        });
    };

    const handleReject = () => {
        if (!rejectReason) {
            toast.error("Pick a reject reason first");
            return;
        }
        const reason = rejectReason === "other" ? (rejectNote.trim() || "other") : rejectReason;
        if (rejectReason === "other" && !rejectNote.trim()) {
            toast.error("Add a short note for 'Other'");
            return;
        }
        rejectDraft(
            { id: draft.id, reason },
            {
                onSuccess: () => {
                    setLocalStatus("REJECTED");
                    toast.success("Draft rejected.");
                    onOpenChange(false);
                },
                onError: (err: any) => toast.error(`Rejection failed: ${err.message}`),
            }
        );
    };

    const handleIgnore = () => {
        ignoreDraft(draft.id, {
            onSuccess: () => {
                setLocalStatus("IGNORED");
                toast.message("Draft ignored.");
                onOpenChange(false);
            },
            onError: (err: any) => toast.error(`Failed: ${err.message}`),
        });
    };

    // Keyboard shortcuts
    React.useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (!isOpen || isBusy) return;
            if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;

            if (e.key.toLowerCase() === "o" && localStatus === "PENDING") {
                e.preventDefault();
                handleOpenAndCopy();
            } else if (e.key.toLowerCase() === "r" && localStatus === "PENDING") {
                e.preventDefault();
                setShowReject((v) => !v);
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen, isBusy, localStatus, copyPayload, isDirty]);

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent side="right" className="w-[85vw] sm:w-[50vw] p-0 flex flex-col border-l border-border/40 shadow-2xl">
                <SheetHeader className="h-14 px-6 border-b border-border/40 flex flex-row items-center justify-between space-y-0 bg-background/50 backdrop-blur sticky top-0 z-10">
                    <div className="flex items-center gap-3 overflow-hidden">
                        <SheetTitle className="text-sm font-bold tracking-tight">Review Draft</SheetTitle>
                        <Badge variant="outline" className="font-mono text-[9px] h-4 leading-none opacity-50 px-1">#{draft.id}</Badge>
                        <Badge variant="outline" className="text-[9px] font-bold h-4 px-1">{draft.platform}</Badge>
                        {draft.angle_name && (
                            <Badge variant="secondary" className="text-[9px] font-mono h-4 px-1.5 truncate max-w-[140px]">{draft.angle_name}</Badge>
                        )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        {localStatus === "PENDING" && (
                            <>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 text-xs font-bold px-3 text-red-500 hover:text-red-400"
                                    onClick={() => setShowReject((v) => !v)}
                                    disabled={isBusy}
                                >
                                    <XCircle className="mr-1.5 h-3.5 w-3.5" />
                                    Reject
                                </Button>
                                <Button
                                    variant="default"
                                    size="sm"
                                    className="h-8 text-xs font-bold px-4"
                                    onClick={handleOpenAndCopy}
                                    disabled={isBusy || isDirty}
                                >
                                    <ClipboardCheck className="mr-2 h-3.5 w-3.5" />
                                    {isDirty ? "Saving..." : "Open & Copy"}
                                    <span className="ml-2 opacity-30 text-[10px] hidden sm:inline">[O]</span>
                                </Button>
                            </>
                        )}
                        {localStatus === "AWAITING_CONFIRM" && (
                            <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-[10px] font-bold py-1 h-6 px-2">
                                AWAITING CONFIRMATION
                            </Badge>
                        )}
                        {localStatus === "POSTED" && (
                            <Badge className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] font-bold py-1 h-6 px-2">POSTED</Badge>
                        )}
                        {localStatus === "REJECTED" && (
                            <Badge className="bg-red-500/10 text-red-500 border-red-500/20 text-[10px] font-bold py-1 h-6 px-2">REJECTED</Badge>
                        )}
                    </div>
                </SheetHeader>

                {showReject && localStatus === "PENDING" && (
                    <div className="px-6 py-4 border-b border-border/40 bg-red-500/5 space-y-3">
                        <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Reject reason</span>
                        <div className="flex flex-wrap gap-2">
                            {REJECT_REASONS.map((r) => (
                                <button
                                    key={r.id}
                                    onClick={() => setRejectReason(r.id)}
                                    className={`h-7 px-3 rounded-full text-[10px] font-bold border transition-colors ${
                                        rejectReason === r.id
                                            ? "bg-red-500/20 text-red-500 border-red-500/40"
                                            : "bg-muted/20 text-muted-foreground border-border/40 hover:text-foreground"
                                    }`}
                                >
                                    {r.label}
                                </button>
                            ))}
                        </div>
                        {rejectReason === "other" && (
                            <Input
                                placeholder="Add a short note..."
                                className="h-8 text-xs"
                                value={rejectNote}
                                onChange={(e) => setRejectNote(e.target.value)}
                            />
                        )}
                        <div className="flex justify-end gap-2">
                            <Button variant="ghost" size="sm" className="h-7 text-[10px]" onClick={() => setShowReject(false)}>Cancel</Button>
                            <Button variant="destructive" size="sm" className="h-7 text-[10px]" onClick={handleReject} disabled={isRejecting}>
                                {isRejecting ? "Rejecting..." : "Confirm Reject"}
                            </Button>
                        </div>
                    </div>
                )}

                {localStatus === "AWAITING_CONFIRM" && (
                    <div className="px-6 py-4 border-b border-border/40 bg-blue-500/5 space-y-3">
                        <p className="text-xs text-muted-foreground">
                            Paste and submit the reply in your platform tab, then confirm what happened here.
                        </p>
                        <Input
                            placeholder="Live URL of the posted reply (optional)"
                            className="h-8 text-xs"
                            value={liveUrl}
                            onChange={(e) => setLiveUrl(e.target.value)}
                        />
                        <div className="flex gap-2">
                            <Button size="sm" className="h-8 text-[11px] font-bold flex-1" onClick={handleConfirmPosted} disabled={isConfirming}>
                                <Check className="mr-1.5 h-3.5 w-3.5" />
                                {isConfirming ? "Confirming..." : "I posted it"}
                            </Button>
                            <Button variant="outline" size="sm" className="h-8 text-[11px] font-bold flex-1" onClick={handleDidntPost} disabled={isUnconfirming}>
                                <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                                {isUnconfirming ? "Reverting..." : "Didn't post"}
                            </Button>
                        </div>
                    </div>
                )}

                <div className="flex-1 flex overflow-hidden">
                    {/* Left Pane: Source Context */}
                    <div className="flex-1 overflow-y-auto border-r border-border/40 bg-muted/10 p-6 space-y-6">
                        <section>
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                                    <MessageSquare className="h-3 w-3" /> Source Context
                                </h3>
                                {draft.url && (
                                    <a href={draft.url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-primary hover:underline flex items-center gap-1 font-medium">
                                        Open Source <ExternalLink className="h-2.5 w-2.5" />
                                    </a>
                                )}
                            </div>
                            <div className="rounded border border-border/40 bg-background p-4 relative overflow-hidden group">
                                <div className="absolute top-0 left-0 w-1 h-full bg-primary/20" />
                                {draft.author_name && (
                                    <div className="text-[10px] text-muted-foreground mb-2 font-mono">
                                        {draft.author_name}{draft.author_headline ? ` — ${draft.author_headline}` : ""}
                                    </div>
                                )}
                                <h4 className="text-sm font-bold mb-3 leading-snug">{draft.title}</h4>
                                <blockquote className="text-sm text-foreground/80 font-medium leading-relaxed italic border-l-2 border-primary/10 pl-4 py-1 whitespace-pre-wrap">
                                    {draft.original_content}
                                </blockquote>
                            </div>
                        </section>

                        <section className="space-y-3">
                            <h3 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                                <Zap className="h-3 w-3" /> Provenance
                            </h3>
                            <div className="grid grid-cols-2 gap-2">
                                <div className="rounded border border-border/40 bg-background p-3">
                                    <span className="text-[9px] font-mono uppercase text-muted-foreground block mb-1">Angle</span>
                                    <span className="text-xs font-bold font-mono">{draft.angle_name || "—"}</span>
                                </div>
                                <div className="rounded border border-border/40 bg-background p-3 relative group">
                                    <span className="text-[9px] font-mono uppercase text-muted-foreground block mb-1">Confidence</span>
                                    <Popover>
                                        <PopoverTrigger>
                                            <div className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity">
                                                <Badge className={`${draft.confidence > 0.8 ? "bg-green-500/10 text-green-500" : "bg-amber-500/10 text-amber-500"} border-transparent text-[11px] font-bold h-5`}>
                                                    {(draft.confidence * 100).toFixed(0)}%
                                                </Badge>
                                                <Info className="h-3 w-3 text-muted-foreground opacity-30" />
                                            </div>
                                        </PopoverTrigger>
                                        <PopoverContent className="w-80">
                                            <PopoverHeader>
                                                <PopoverTitle className="text-xs font-bold flex items-center gap-2">
                                                    <BrainCircuit className="h-3.5 w-3.5 text-primary" />
                                                    Triage Reasoning
                                                </PopoverTitle>
                                            </PopoverHeader>
                                            <div className="text-xs leading-relaxed text-muted-foreground p-1 font-medium italic">
                                                "{draft.triage_reasoning || "No detailed reasoning available for this generation."}"
                                            </div>
                                        </PopoverContent>
                                    </Popover>
                                </div>
                            </div>
                        </section>

                        {localStatus !== "PENDING" && (
                            <div className="flex justify-end">
                                <Button variant="ghost" size="sm" className="h-7 text-[10px] text-muted-foreground" onClick={handleIgnore} disabled={isIgnoring}>
                                    <Ban className="mr-1.5 h-3 w-3" /> Ignore
                                </Button>
                            </div>
                        )}
                    </div>

                    {/* Right Pane: AI Editor */}
                    <div className="flex-1 flex flex-col overflow-hidden p-6 space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
                                <Zap className="h-3 w-3 animate-pulse text-primary fill-primary/20" /> Draft Editor
                            </h3>
                            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopyOnly} disabled={!copyPayload}>
                                {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
                            </Button>
                        </div>
                        <div className="flex-1 relative">
                            <Textarea
                                value={editedText}
                                onChange={(e) => setEditedText(e.target.value)}
                                className="h-full resize-none border-none p-0 text-sm leading-relaxed focus-visible:ring-0 bg-transparent font-medium"
                                placeholder="Edit your response here..."
                                disabled={isBusy || localStatus !== "PENDING"}
                            />
                        </div>

                        <div className="pt-4 border-t border-border/40">
                            <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono font-medium">
                                <span>
                                    {editedText.length} chars
                                    {isDirty && " · saving..."}
                                    {!isDirty && copyReady && " · saved"}
                                </span>
                                <button
                                    className="hover:text-foreground disabled:opacity-50"
                                    onClick={() => setEditedText(draft.ai_draft_text)}
                                    disabled={isBusy || localStatus !== "PENDING"}
                                >Reset</button>
                            </div>
                        </div>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}

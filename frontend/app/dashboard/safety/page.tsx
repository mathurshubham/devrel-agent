"use client";

import { useState } from "react";
import {
    Plus,
    ShieldCheck,
    MoreHorizontal,
    Search,
    Loader2,
    Trash2,
    Edit2,
    AlertCircle,
    CheckCircle2,
    XCircle
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import {
    useSafetyProfiles,
    useCreateSafetyProfile,
    useUpdateSafetyProfile,
    useDeleteSafetyProfile,
    type SubredditSafetyProfile,
    type SubredditSafetyProfileCreate
} from "@/hooks/use-safety";

export default function SafetyProfilesPage() {
    const { data: profiles, isLoading } = useSafetyProfiles();
    const createMutation = useCreateSafetyProfile();
    const updateMutation = useUpdateSafetyProfile();
    const deleteMutation = useDeleteSafetyProfile();

    const [isDialogOpen, setIsDialogOpen] = useState(false);
    const [editingProfile, setEditingProfile] = useState<SubredditSafetyProfile | null>(null);
    const [searchQuery, setSearchQuery] = useState("");

    // Form State
    const [formData, setFormData] = useState<SubredditSafetyProfileCreate>({
        subreddit_name: "",
        allow_auto_pilot: true,
        max_daily_posts: 5,
        require_manual_review: false,
        notes: ""
    });

    const handleOpenDialog = (profile?: SubredditSafetyProfile) => {
        if (profile) {
            setEditingProfile(profile);
            setFormData({
                subreddit_name: profile.subreddit_name,
                allow_auto_pilot: profile.allow_auto_pilot,
                max_daily_posts: profile.max_daily_posts,
                require_manual_review: profile.require_manual_review,
                notes: profile.notes || ""
            });
        } else {
            setEditingProfile(null);
            setFormData({
                subreddit_name: "",
                allow_auto_pilot: true,
                max_daily_posts: 5,
                require_manual_review: false,
                notes: ""
            });
        }
        setIsDialogOpen(true);
    };

    const handleSave = async () => {
        if (!formData.subreddit_name) {
            toast.error("Subreddit name is required");
            return;
        }

        try {
            if (editingProfile) {
                await updateMutation.mutateAsync({
                    ...formData,
                    id: editingProfile.id,
                    org_id: editingProfile.org_id
                });
                toast.success("Safety profile updated");
            } else {
                await createMutation.mutateAsync(formData);
                toast.success("Safety profile created");
            }
            setIsDialogOpen(false);
        } catch (err: any) {
            toast.error(err.response?.data?.detail || "Failed to save profile");
        }
    };

    const handleDelete = async (id: number) => {
        if (!confirm("Are you sure you want to delete this safety profile?")) return;
        try {
            await deleteMutation.mutateAsync(id);
            toast.success("Profile deleted");
        } catch (err) {
            toast.error("Failed to delete profile");
        }
    };

    const filteredProfiles = profiles?.filter(p =>
        p.subreddit_name.toLowerCase().includes(searchQuery.toLowerCase())
    );

    if (isLoading) {
        return (
            <div className="flex h-[calc(100vh-200px)] items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-6 p-8 max-w-6xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 text-foreground">
                        <ShieldCheck className="h-5 w-5 text-primary" />
                        <h1 className="text-xl font-semibold tracking-tight">Subreddit Safety Profiles</h1>
                    </div>
                    <p className="text-sm text-muted-foreground">
                        Configure AI guardrails and autopilot permissions for specific communities.
                    </p>
                </div>
                <Button onClick={() => handleOpenDialog()} className="gap-2">
                    <Plus className="h-4 w-4" />
                    New Profile
                </Button>
            </div>

            {/* List & Search */}
            <div className="flex flex-col gap-4 border border-border/40 rounded-md bg-background overflow-hidden shadow-sm">
                <div className="p-4 border-b border-border/40 bg-muted/5 flex items-center gap-3">
                    <div className="relative flex-1 max-w-sm">
                        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                        <Input
                            placeholder="Filter by subreddit..."
                            className="pl-9 h-9 text-sm shadow-none border-border/40"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                </div>

                <div className="overflow-x-auto text-sm">
                    <Table>
                        <TableHeader className="bg-muted/10">
                            <TableRow className="hover:bg-transparent">
                                <TableHead className="w-[200px] py-3 text-[10px] uppercase font-mono tracking-widest">Subreddit</TableHead>
                                <TableHead className="py-3 text-[10px] uppercase font-mono tracking-widest text-center">Auto-Pilot</TableHead>
                                <TableHead className="py-3 text-[10px] uppercase font-mono tracking-widest text-center">Daily Limit</TableHead>
                                <TableHead className="py-3 text-[10px] uppercase font-mono tracking-widest text-center">Manual Review</TableHead>
                                <TableHead className="py-3 text-[10px] uppercase font-mono tracking-widest">Notes</TableHead>
                                <TableHead className="w-[50px] py-3"></TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {filteredProfiles?.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={6} className="h-32 text-center text-muted-foreground italic">
                                        No safety profiles found. Create one to get started.
                                    </TableCell>
                                </TableRow>
                            ) : (
                                filteredProfiles?.map((profile) => (
                                    <TableRow key={profile.id} className="group transition-colors border-border/40">
                                        <TableCell className="font-mono text-xs font-semibold py-4">
                                            r/{profile.subreddit_name}
                                        </TableCell>
                                        <TableCell className="text-center">
                                            {profile.allow_auto_pilot ? (
                                                <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-[10px] uppercase font-mono py-0 h-4">Enabled</Badge>
                                            ) : (
                                                <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20 text-[10px] uppercase font-mono py-0 h-4">Disabled</Badge>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-center font-mono text-xs">
                                            {profile.max_daily_posts} posts
                                        </TableCell>
                                        <TableCell className="text-center">
                                            {profile.require_manual_review ? (
                                                <AlertCircle className="h-4 w-4 text-amber-500 mx-auto" />
                                            ) : (
                                                <CheckCircle2 className="h-4 w-4 text-green-500 mx-auto" strokeWidth={1} />
                                            )}
                                        </TableCell>
                                        <TableCell className="max-w-[200px] truncate text-muted-foreground text-xs">
                                            {profile.notes || "—"}
                                        </TableCell>
                                        <TableCell>
                                            <DropdownMenu>
                                                <DropdownMenuTrigger render={<Button variant="ghost" className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100" />}>
                                                    <MoreHorizontal className="h-4 w-4" />
                                                </DropdownMenuTrigger>
                                                <DropdownMenuContent align="end" className="w-[160px] border-border/40 shadow-xl">
                                                    <DropdownMenuItem onClick={() => handleOpenDialog(profile)} className="gap-2 text-xs">
                                                        <Edit2 className="h-3.5 w-3.5" />
                                                        Edit Profile
                                                    </DropdownMenuItem>
                                                    <DropdownMenuItem onClick={() => handleDelete(profile.id)} className="gap-2 text-xs text-destructive focus:text-destructive">
                                                        <Trash2 className="h-3.5 w-3.5" />
                                                        Delete
                                                    </DropdownMenuItem>
                                                </DropdownMenuContent>
                                            </DropdownMenu>
                                        </TableCell>
                                    </TableRow>
                                ))
                            )}
                        </TableBody>
                    </Table>
                </div>
            </div>

            {/* Dialog */}
            <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
                <DialogContent className="max-w-md border-border/40 shadow-2xl">
                    <DialogHeader>
                        <DialogTitle className="text-base tracking-tight">{editingProfile ? "Edit Safety Profile" : "New Safety Profile"}</DialogTitle>
                        <DialogDescription className="text-xs">
                            Define community-specific guardrails for r/{formData.subreddit_name || "..."}
                        </DialogDescription>
                    </DialogHeader>

                    <div className="grid gap-5 py-4">
                        <div className="grid gap-2">
                            <label className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Subreddit Name</label>
                            <div className="flex items-center gap-2">
                                <span className="text-muted-foreground font-mono">r/</span>
                                <Input
                                    placeholder="e.g. reactjs"
                                    className="h-9 text-sm font-mono shadow-none"
                                    value={formData.subreddit_name}
                                    onChange={(e) => setFormData({ ...formData, subreddit_name: e.target.value.toLowerCase() })}
                                    disabled={!!editingProfile}
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="flex flex-col gap-2 p-3 rounded-md border border-border/40 bg-muted/5">
                                <div className="flex items-center justify-between">
                                    <label className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Auto-Pilot</label>
                                    <Checkbox
                                        checked={formData.allow_auto_pilot}
                                        onCheckedChange={(checked) => setFormData({ ...formData, allow_auto_pilot: !!checked })}
                                    />
                                </div>
                                <p className="text-[10px] text-muted-foreground leading-snug">Allow AI to post directly without manual approval.</p>
                            </div>
                            <div className="flex flex-col gap-2 p-3 rounded-md border border-border/40 bg-muted/5">
                                <div className="flex items-center justify-between">
                                    <label className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Req. Review</label>
                                    <Checkbox
                                        checked={formData.require_manual_review}
                                        onCheckedChange={(checked) => setFormData({ ...formData, require_manual_review: !!checked })}
                                    />
                                </div>
                                <p className="text-[10px] text-muted-foreground leading-snug">Always force manual human review for all drafts.</p>
                            </div>
                        </div>

                        <div className="grid gap-2">
                            <div className="flex justify-between items-center">
                                <label className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Max Daily Posts</label>
                                <span className="text-xs font-mono font-bold text-primary">{formData.max_daily_posts}</span>
                            </div>
                            <Input
                                type="number"
                                className="h-9 text-sm font-mono shadow-none"
                                value={formData.max_daily_posts}
                                onChange={(e) => setFormData({ ...formData, max_daily_posts: parseInt(e.target.value) })}
                            />
                        </div>

                        <div className="grid gap-2">
                            <label className="text-[10px] uppercase font-mono tracking-widest text-muted-foreground">Internal Notes</label>
                            <Textarea
                                placeholder="Why these guardrails exist for this community..."
                                className="resize-none min-h-[80px] text-xs shadow-none"
                                value={formData.notes}
                                onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                            />
                        </div>
                    </div>

                    <DialogFooter className="bg-muted/30 -mx-6 -mb-6 p-4 border-t border-border/40">
                        <Button variant="ghost" size="sm" className="text-[10px] uppercase font-mono" onClick={() => setIsDialogOpen(false)}>Cancel</Button>
                        <Button
                            size="sm"
                            className="text-[10px] uppercase font-mono px-6"
                            onClick={handleSave}
                            disabled={createMutation.isPending || updateMutation.isPending}
                        >
                            {editingProfile ? "Save Changes" : "Create Profile"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}

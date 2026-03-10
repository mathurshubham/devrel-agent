"use client";

import * as React from "react";
import { Plus, Play, Pause, Activity, Loader2, ArrowUpDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { CreateCampaignDialog } from "@/components/campaigns/create-dialog";
import { useCampaigns, useToggleCampaignStatus, Campaign } from "@/hooks/use-campaigns";
import { toast } from "sonner";

const StatusBadge = ({ status }: { status: string }) => {
    switch (status) {
        case "ACTIVE":
            return (
                <Badge className="bg-green-500/10 text-green-500 border-green-500/20 px-1.5 py-0 text-[10px] font-bold tracking-tight">
                    ACTIVE
                </Badge>
            );
        case "PAUSED":
            return (
                <Badge variant="outline" className="bg-muted text-muted-foreground border-border/40 px-1.5 py-0 text-[10px] font-bold tracking-tight">
                    PAUSED
                </Badge>
            );
        default:
            return <Badge variant="secondary" className="text-[10px] font-bold tracking-tight">{status}</Badge>;
    }
};

export default function CampaignsPage() {
    const [isDialogOpen, setIsDialogOpen] = React.useState(false);
    const { data: campaigns = [], isLoading } = useCampaigns();
    const { mutate: toggleStatus, isPending: isToggling } = useToggleCampaignStatus();

    const handleToggle = (campaign: Campaign) => {
        const newStatus = campaign.status === "ACTIVE" ? "PAUSED" : "ACTIVE";
        toggleStatus(
            { id: campaign.id, status: newStatus },
            {
                onSuccess: () => {
                    toast.success(`Campaign r/${campaign.subreddit_name} ${newStatus.toLowerCase()}`);
                },
                onError: (error: any) => {
                    toast.error(`Failed to toggle status: ${error.message}`);
                },
            }
        );
    };

    return (
        <div className="flex flex-col h-full bg-background">
            <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 bg-background/50 sticky top-0 z-20 backdrop-blur">
                <div className="flex items-center gap-4">
                    <h1 className="text-sm font-bold tracking-tight uppercase flex items-center gap-2">
                        <Activity className="h-4 w-4 text-primary" />
                        Campaigns
                    </h1>
                </div>
                <Button
                    onClick={() => setIsDialogOpen(true)}
                    size="sm"
                    className="h-9 bg-primary text-primary-foreground text-xs font-bold px-4"
                >
                    <Plus className="mr-2 h-3.5 w-3.5" />
                    New Campaign
                </Button>
            </div>

            <div className="flex-1 overflow-auto">
                <Table className="border-collapse">
                    <TableHeader className="bg-muted/30 sticky top-0 z-10">
                        <TableRow className="hover:bg-transparent border-b border-border/40">
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground py-3 px-6">Status</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Community</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground min-w-[300px]">Keywords</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground">Poll Freq</TableHead>
                            <TableHead className="text-xs font-mono uppercase text-muted-foreground text-right px-6">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {isLoading ? (
                            Array.from({ length: 5 }).map((_, i) => (
                                <TableRow key={i} className="border-b border-border/40 animate-pulse">
                                    <TableCell className="px-6"><div className="h-5 w-16 bg-muted rounded" /></TableCell>
                                    <TableCell><div className="h-4 w-32 bg-muted rounded" /></TableCell>
                                    <TableCell>
                                        <div className="flex gap-2">
                                            <div className="h-4 w-12 bg-muted rounded" />
                                            <div className="h-4 w-16 bg-muted rounded" />
                                            <div className="h-4 w-10 bg-muted rounded" />
                                        </div>
                                    </TableCell>
                                    <TableCell><div className="h-4 w-12 bg-muted rounded" /></TableCell>
                                    <TableCell className="text-right px-6"><div className="h-8 w-8 bg-muted rounded ml-auto" /></TableCell>
                                </TableRow>
                            ))
                        ) : campaigns.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={5} className="h-64 text-center">
                                    <div className="flex flex-col items-center justify-center gap-2 opacity-50">
                                        <Activity className="h-8 w-8" />
                                        <p className="text-sm font-medium">No active campaigns found</p>
                                        <p className="text-xs">Create your first one to start monitoring subreddits</p>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ) : (
                            campaigns.map((campaign) => (
                                <TableRow
                                    key={campaign.id}
                                    className="group hover:bg-muted/40 border-b border-border/40 transition-colors"
                                >
                                    <TableCell className="px-6"><StatusBadge status={campaign.status} /></TableCell>
                                    <TableCell>
                                        <div className="flex flex-col gap-0.5">
                                            <span className="text-sm font-semibold">r/{campaign.subreddit_name}</span>
                                            <span className="text-[10px] text-muted-foreground font-mono opacity-50">{campaign.id}</span>
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex flex-wrap gap-1.5 items-center">
                                            {campaign.keywords.slice(0, 3).map((keyword, idx) => (
                                                <Badge key={idx} variant="secondary" className="text-[9px] px-1.5 py-0 h-4 font-medium lowercase">
                                                    {keyword}
                                                </Badge>
                                            ))}
                                            {campaign.keywords.length > 3 && (
                                                <span className="text-[9px] text-muted-foreground font-mono">
                                                    +{campaign.keywords.length - 3} more
                                                </span>
                                            )}
                                            {campaign.keywords.length === 0 && (
                                                <span className="text-[10px] text-muted-foreground italic">No keywords set</span>
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <span className="text-xs font-mono text-muted-foreground tabular-nums">
                                            {campaign.poll_frequency_minutes}m
                                        </span>
                                    </TableCell>
                                    <TableCell className="text-right px-6">
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                            onClick={() => handleToggle(campaign)}
                                            disabled={isToggling}
                                        >
                                            {isToggling ? (
                                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                            ) : campaign.status === "ACTIVE" ? (
                                                <Pause className="h-3.5 w-3.5" />
                                            ) : (
                                                <Play className="h-3.5 w-3.5" />
                                            )}
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>

            <CreateCampaignDialog isOpen={isDialogOpen} onOpenChange={setIsDialogOpen} />
        </div>
    );
}

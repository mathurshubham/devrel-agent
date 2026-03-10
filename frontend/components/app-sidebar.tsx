"use strict";

import * as React from "react";
import {
    BarChart3,
    Inbox,
    Settings,
    ShieldCheck,
    Terminal,
    LayoutDashboard,
    ChevronRight,
    MoreHorizontal,
    Plus
} from "lucide-react";

import {
    Sidebar,
    SidebarContent,
    SidebarFooter,
    SidebarHeader,
    SidebarMenu,
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarMenuSub,
    SidebarMenuSubButton,
    SidebarMenuSubItem,
    SidebarGroup,
    SidebarGroupLabel,
    SidebarGroupContent,
    SidebarProvider,
    SidebarTrigger,
    SidebarInset,
} from "@/components/ui/sidebar";

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const items = [
    {
        title: "Dashboard",
        url: "/dashboard",
        icon: LayoutDashboard,
    },
    {
        title: "Draft Inbox",
        url: "/dashboard/inbox",
        icon: Inbox,
    },
    {
        title: "Campaigns",
        url: "/dashboard/campaigns",
        icon: BarChart3,
    },
    {
        title: "Safety Profiles",
        url: "/dashboard/safety",
        icon: ShieldCheck,
    },
    {
        title: "Settings",
        url: "/dashboard/settings",
        icon: Settings,
    },
];

export function AppSidebar() {
    return (
        <Sidebar collapsible="icon" className="border-r border-border/40">
            <SidebarHeader className="h-16 flex items-center px-6 border-b border-border/40">
                <div className="flex items-center gap-2 font-semibold">
                    <Terminal className="h-5 w-5 text-primary" />
                    <span className="group-data-[collapsible=icon]:hidden">TryEval</span>
                </div>
            </SidebarHeader>
            <SidebarContent>
                <SidebarGroup>
                    <SidebarGroupLabel>Navigation</SidebarGroupLabel>
                    <SidebarGroupContent>
                        <SidebarMenu>
                            {items.map((item) => (
                                <SidebarMenuItem key={item.title}>
                                    <SidebarMenuButton asChild tooltip={item.title}>
                                        <a href={item.url}>
                                            <item.icon />
                                            <span>{item.title}</span>
                                        </a>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            ))}
                        </SidebarMenu>
                    </SidebarGroupContent>
                </SidebarGroup>
            </SidebarContent>
            <SidebarFooter className="border-t border-border/40 p-4">
                {/* Placeholder for User Profile/Org Switcher */}
                <div className="flex items-center gap-3 px-2">
                    <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                        <Settings className="h-4 w-4" />
                    </div>
                    <div className="flex flex-col group-data-[collapsible=icon]:hidden">
                        <span className="text-xs font-medium">Organization</span>
                        <span className="text-[10px] text-muted-foreground uppercase">org:admin</span>
                    </div>
                </div>
            </SidebarFooter>
        </Sidebar>
    );
}

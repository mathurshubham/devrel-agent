"use client";

import React from "react";
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
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { dark } from "@clerk/themes";

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
        <Sidebar collapsible="icon" className="border-r border-border/40 bg-zinc-950 dark:bg-zinc-950">
            <SidebarHeader className="h-14 flex items-center px-4 border-b border-border/40 bg-zinc-950">
                <div className="flex items-center gap-2.1 font-bold tracking-tighter text-sm uppercase">
                    <div className="h-6 w-6 rounded bg-primary flex items-center justify-center">
                        <Terminal className="h-3.5 w-3.5 text-primary-foreground" />
                    </div>
                    <span className="group-data-[collapsible=icon]:hidden">Sentinel</span>
                </div>
            </SidebarHeader>
            <SidebarContent className="bg-zinc-950">
                <SidebarGroup>
                    <SidebarGroupLabel className="text-[10px] font-mono uppercase tracking-widest opacity-50 px-2 py-4">Main Ops</SidebarGroupLabel>
                    <SidebarGroupContent>
                        <SidebarMenu>
                            {items.map((item) => (
                                <SidebarMenuItem key={item.title}>
                                    <SidebarMenuButton
                                        asChild
                                        tooltip={item.title}
                                        className="hover:bg-zinc-900 transition-none rounded-none border-l-2 border-transparent data-[active=true]:border-primary data-[active=true]:bg-zinc-900"
                                    >
                                        <a href={item.url} className="flex items-center gap-3 px-3 py-2">
                                            <item.icon className="h-4 w-4 opacity-70" />
                                            <span className="text-xs font-medium tracking-tight group-data-[collapsible=icon]:hidden">{item.title}</span>
                                        </a>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            ))}
                        </SidebarMenu>
                    </SidebarGroupContent>
                </SidebarGroup>
            </SidebarContent>
            <SidebarFooter className="border-t border-border/40 p-2 bg-zinc-950 flex flex-row items-center justify-between gap-2">
                <div className="flex-1 overflow-hidden">
                    <OrganizationSwitcher
                        appearance={{
                            baseTheme: dark,
                            variables: {
                                colorPrimary: '#fafafa',
                                colorBackground: '#09090b',
                                colorText: '#fafafa',
                            },
                            elements: {
                                rootBox: "w-full",
                                organizationSwitcherTrigger: "w-full px-2 py-1.5 hover:bg-zinc-900 transition-colors rounded-md shadow-none border-none",
                                organizationPreviewTextContainer: "group-data-[collapsible=icon]:hidden",
                                organizationSwitcherTriggerIcon: "group-data-[collapsible=icon]:hidden",
                                organizationPreviewMainIdentifier: "text-xs font-bold leading-none tracking-tight",
                                organizationPreviewSecondaryIdentifier: "text-[9px] text-muted-foreground font-mono mt-1 opacity-50 uppercase font-bold",
                                popupBox: "border border-border/40 bg-zinc-950 shadow-2xl",
                            }
                        }}
                    />
                </div>
                <div className="flex shrink-0">
                    <UserButton
                        appearance={{
                            baseTheme: dark,
                            variables: {
                                colorPrimary: '#fafafa',
                                colorBackground: '#09090b',
                                colorText: '#fafafa',
                            },
                            elements: {
                                userButtonTrigger: "hover:bg-zinc-900 transition-colors rounded-md shadow-none p-1",
                                userButtonPopoverCard: "border border-border/40 bg-zinc-950 shadow-2xl",
                                userButtonPopoverFooter: "hidden", // Clean, minimal look
                            }
                        }}
                    />
                </div>
            </SidebarFooter>
        </Sidebar>
    );
}

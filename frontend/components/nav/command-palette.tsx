"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
    Inbox,
    Megaphone,
    Library,
    Shield,
    Settings,
    Cpu,
    Database,
    Radar,
    LineChart,
} from "lucide-react";

import {
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
} from "@/components/ui/command";

export function CommandPalette() {
    const [open, setOpen] = React.useState(false);
    const router = useRouter();

    React.useEffect(() => {
        const down = (e: KeyboardEvent) => {
            if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                setOpen((open) => !open);
            }
        };

        document.addEventListener("keydown", down);
        return () => document.removeEventListener("keydown", down);
    }, []);

    const runCommand = React.useCallback((command: () => void) => {
        setOpen(false);
        command();
    }, []);

    return (
        <CommandDialog open={open} onOpenChange={setOpen}>
            <CommandInput placeholder="Type a command or search..." />
            <CommandList className="max-h-[300px] overflow-y-auto">
                <CommandEmpty>No results found.</CommandEmpty>

                <CommandGroup heading="Workflows" className="text-xs font-mono uppercase tracking-widest text-muted-foreground px-2 py-1.5">
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/inbox"))}
                        className="text-sm py-2"
                    >
                        <Inbox className="mr-2 h-4 w-4 opacity-70" />
                        <span>Draft Inbox</span>
                    </CommandItem>
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/campaigns"))}
                        className="text-sm py-2"
                    >
                        <Megaphone className="mr-2 h-4 w-4 opacity-70" />
                        <span>Campaigns</span>
                    </CommandItem>
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/intel"))}
                        className="text-sm py-2"
                    >
                        <Radar className="mr-2 h-4 w-4 opacity-70" />
                        <span>Intel</span>
                    </CommandItem>
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/analytics"))}
                        className="text-sm py-2"
                    >
                        <LineChart className="mr-2 h-4 w-4 opacity-70" />
                        <span>Analytics</span>
                    </CommandItem>
                </CommandGroup>

                <CommandSeparator className="bg-border/40" />

                <CommandGroup heading="Configuration" className="text-xs font-mono uppercase tracking-widest text-muted-foreground px-2 py-1.5">
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/prompts"))}
                        className="text-sm py-2"
                    >
                        <Library className="mr-2 h-4 w-4 opacity-70" />
                        <span>Prompt Library</span>
                    </CommandItem>
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/safety"))}
                        className="text-sm py-2"
                    >
                        <Shield className="mr-2 h-4 w-4 opacity-70" />
                        <span>Subreddit Safety Profiles</span>
                    </CommandItem>
                </CommandGroup>

                <CommandSeparator className="bg-border/40" />

                <CommandGroup heading="System & Vaults" className="text-xs font-mono uppercase tracking-widest text-muted-foreground px-2 py-1.5">
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/settings"))}
                        className="text-sm py-2"
                    >
                        <Cpu className="mr-2 h-4 w-4 opacity-70" />
                        <span>LLM Configuration</span>
                    </CommandItem>
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/settings"))}
                        className="text-sm py-2"
                    >
                        <Database className="mr-2 h-4 w-4 opacity-70" />
                        <span>Apify Keys</span>
                    </CommandItem>
                    <CommandItem
                        onSelect={() => runCommand(() => router.push("/dashboard/settings"))}
                        className="text-sm py-2"
                    >
                        <Settings className="mr-2 h-4 w-4 opacity-70" />
                        <span>System Settings</span>
                    </CommandItem>
                </CommandGroup>
            </CommandList>
        </CommandDialog>
    );
}

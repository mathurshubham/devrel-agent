"use client";

import { OrganizationList } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
import { useTheme } from "next-themes";
import { Terminal } from "lucide-react";

export default function SelectOrgPage() {
    const { theme } = useTheme();
    const isDark = theme === "dark";

    return (
        <div className="flex min-h-screen w-full flex-col items-center justify-center gap-8 bg-background px-4">
            <div className="flex items-center gap-2 font-bold tracking-tighter text-sm uppercase">
                <div className="h-7 w-7 rounded bg-primary flex items-center justify-center">
                    <Terminal className="h-4 w-4 text-primary-foreground" />
                </div>
                <span>Sentinel</span>
            </div>

            <div className="flex flex-col items-center gap-1 text-center">
                <h1 className="text-lg font-semibold tracking-tight">Choose an organization</h1>
                <p className="text-sm text-muted-foreground max-w-sm">
                    Sentinel is multi-tenant — select or create an organization to continue to your inbox.
                </p>
            </div>

            <OrganizationList
                hidePersonal
                afterSelectOrganizationUrl="/dashboard/inbox"
                afterCreateOrganizationUrl="/dashboard/inbox"
                appearance={{
                    baseTheme: isDark ? dark : undefined,
                    variables: {
                        colorPrimary: isDark ? "#fafafa" : "#09090b",
                        colorBackground: isDark ? "#09090b" : "#ffffff",
                        colorText: isDark ? "#fafafa" : "#09090b",
                    },
                    elements: {
                        rootBox: "w-full max-w-md",
                        cardBox: "border border-border/40 shadow-2xl w-full",
                    },
                }}
            />
        </div>
    );
}

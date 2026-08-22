"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import {
    Breadcrumb,
    BreadcrumbList,
    BreadcrumbItem,
    BreadcrumbLink,
    BreadcrumbPage,
    BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

// Simple, explicit segment -> label mapping. Add a route here when it
// needs a friendlier breadcrumb label than a title-cased slug.
const SEGMENT_LABELS: Record<string, string> = {
    dashboard: "Sentinel",
    inbox: "Inbox",
    campaigns: "Campaigns",
    prompts: "Prompts",
    safety: "Safety",
    settings: "Settings",
    "select-org": "Select Organization",
    admin: "Admin",
};

function labelFor(segment: string): string {
    return SEGMENT_LABELS[segment] || segment.charAt(0).toUpperCase() + segment.slice(1);
}

export function Breadcrumbs() {
    const pathname = usePathname();
    const segments = pathname.split("/").filter(Boolean);

    // Always root the breadcrumb at "Sentinel -> Dashboard" even off /dashboard.
    const crumbs =
        segments[0] === "dashboard"
            ? segments
            : ["dashboard", ...segments];

    return (
        <Breadcrumb>
            <BreadcrumbList>
                {crumbs.map((segment, idx) => {
                    const href = "/" + crumbs.slice(0, idx + 1).join("/");
                    const isLast = idx === crumbs.length - 1;
                    const label = idx === 0 ? "Sentinel" : labelFor(segment);

                    return (
                        <React.Fragment key={href}>
                            <BreadcrumbItem>
                                {isLast ? (
                                    <BreadcrumbPage className="text-sm font-semibold">{label}</BreadcrumbPage>
                                ) : (
                                    <BreadcrumbLink
                                        href={href}
                                        className={
                                            idx === 0
                                                ? "text-xs font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground"
                                                : "text-sm font-medium"
                                        }
                                    >
                                        {label}
                                    </BreadcrumbLink>
                                )}
                            </BreadcrumbItem>
                            {!isLast && <BreadcrumbSeparator />}
                        </React.Fragment>
                    );
                })}
            </BreadcrumbList>
        </Breadcrumb>
    );
}

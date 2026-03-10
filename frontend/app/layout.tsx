import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { Breadcrumb, BreadcrumbList, BreadcrumbItem, BreadcrumbLink, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { GlobalCommandPalette } from "@/components/global-command";
import { Toaster } from "@/components/ui/sonner";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TryEval | OSS DevRel AI Agent",
  description: "Next-gen campaign management for OSS DevRel",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html lang="en" className="dark">
        <body
          className={`${geistSans.variable} ${geistMono.variable} antialiased font-sans bg-background text-foreground`}
        >
          <TooltipProvider>
            <SidebarProvider>
              <AppSidebar />
              <SidebarInset className="overflow-hidden flex flex-col">
                <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-4">
                  <div className="flex items-center gap-2 flex-1">
                    <SidebarTrigger className="-ml-1 h-8 w-8" />
                    <Separator orientation="vertical" className="mr-2 h-4" />
                    <Breadcrumb>
                      <BreadcrumbList>
                        <BreadcrumbItem>
                          <BreadcrumbLink href="/dashboard" className="text-xs font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground">Sentinel</BreadcrumbLink>
                        </BreadcrumbItem>
                        <BreadcrumbSeparator />
                        <BreadcrumbItem>
                          <BreadcrumbLink href="/dashboard/campaigns" className="text-sm font-medium">Campaigns</BreadcrumbLink>
                        </BreadcrumbItem>
                        <BreadcrumbSeparator />
                        <BreadcrumbItem>
                          <BreadcrumbPage className="text-sm font-semibold">Inbox</BreadcrumbPage>
                        </BreadcrumbItem>
                      </BreadcrumbList>
                    </Breadcrumb>
                  </div>
                  <div className="flex items-center gap-4">
                    <kbd className="pointer-events-none hidden h-5 select-none items-center gap-1 rounded border border-border/40 bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100 sm:flex">
                      <span className="text-xs">⌘</span>K
                    </kbd>
                  </div>
                </header>
                <main className="flex-1 overflow-y-auto bg-background/50">
                  {children}
                </main>
              </SidebarInset>
              <GlobalCommandPalette />
              <Toaster position="bottom-right" />
            </SidebarProvider>
          </TooltipProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}

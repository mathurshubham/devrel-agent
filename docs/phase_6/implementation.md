# Phase 6: Next.js Frontend & Interactive UI

This document outlines the implementation plan for the Sentinel / TryEval OSS DevRel AI Agent's frontend, based on Sections 3.1, 5.6, and 11 of TRD 6.

## User Review Required

> [!IMPORTANT]
> The `frontend/` directory currently contains a `middleware.ts` and `app/api/...` files, but no initialized Next.js application or `package.json`. 
> I will temporarily move these existing files, run `npx create-next-app@latest frontend` to scaffold a clean Next.js 15 project, and then restore the files. Please approve this initialization strategy.

> [!NOTE]
> I will be using `shadcn/ui` with the **Zinc** theme and installing standard dependencies like `@clerk/nextjs`, `@tanstack/react-table`, `lucide-react`, and `sonner`.

## Proposed Changes

---

### Setup & Infrastructure

1. **Next.js Initialization**
   - Temporarily backup existing `frontend/` files.
   - Run `npx create-next-app` initialization.
   - Restore `middleware.ts` and `app/api/...`.
2. **Dependencies**
   - Install React Query, TanStack Table, Clerk Next.js, and shadcn components.

---

### Step 1: Theming, Typography & App Shell

#### [MODIFY] `frontend/app/layout.tsx`
- Implement `ClerkProvider` wrapping the root.
- Apply `next/font/google` (`Inter` for primary, `JetBrains Mono` for monospace).
- Use `shadcn/ui` structural styling (1px `border-border/40` borders).
- Build the App Shell: collapsible left sidebar and sticky top header with dynamic breadcrumbs.

---

### Step 2: App Router & Clerk Middleware

#### [MODIFY] `frontend/middleware.ts`
- Ensure the Clerk middleware perfectly matches Section 3.1 (protecting `/dashboard(.*)` and restricting `/admin(.*)` and `/dashboard/settings(.*)` to `org:admin`). This file already largely implements this, but will verify context and imports with the new setup.

---

### Step 3: Global Command Palette

#### [NEW] `frontend/components/global-command.tsx`
- Implement a ⌘K Command Palette (`CommandDialog` from shadcn).
- Add a subtle backdrop blur.
- Mount at the root layout level so it's accessible everywhere.

---

### Step 4: Draft Inbox

#### [NEW] `frontend/app/dashboard/page.tsx`
- Build the Inbox View utilizing `DataTable` from `@tanstack/react-table`.
- Apply dense row heights (`size="sm"`) and sticky headers.
- Build Status & Confidence Badges based on score rules (Green, Amber, Red).
- Attach shadcn `Popover` triggered by clicking the confidence badge to show `triage_reasoning`.
- Add `Skeleton` loaders matching row height.

---

### Step 5: Draft Review Split-Pane

#### [NEW] `frontend/components/draft-review.tsx`
- Build a split-pane interface.
- **Left Pane:** Original Reddit thread, styled as read-only.
- **Right Pane:** The AI draft form encapsulated within a `Sheet` component.
- **Indicators:** Display `model_used`, `prompt_template_version`, and truncation state.
- **JSON/Prompt Preview:** Inside `<pre>` tags with syntax highlighting and a "Copy to Clipboard" button.
- **Publish Action:** Optimistic React Query mutation hooked into a 3-state `Toast` notification via `sonner`.

## Verification Plan

### Automated Tests
1. **Linter & Type Checker:** Run `npm run lint` and `npx tsc --noEmit` to ensure there are no TypeScript or ESLint errors.
2. **Build Test:** Run `npm run build` to verify Next.js builds successfully.

### Browser Verification
1. **Local Dev Server:** Start the frontend using `npm run dev`.
2. **Browser Subagent:** I will spin up the browser subagent to connect to the local server, navigate the layout, verify the Command Palette visual backdrop, and verify the Draft Inbox and Review Sheet UI elements render as expected.

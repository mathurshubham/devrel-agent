import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';

// Routes that require a signed-in user, but not necessarily an active org.
// /select-org MUST be in this list (not the org-gated one below) so an
// org-less user can actually reach it — putting it behind the org check
// would redirect it to itself forever.
const isAuthRequired = createRouteMatcher(['/dashboard(.*)', '/select-org(.*)', '/admin(.*)']);
// Routes that additionally require an active Clerk organization.
const isOrgRequired = createRouteMatcher(['/dashboard(.*)']);
const isAdminRoute = createRouteMatcher(['/dashboard/settings(.*)', '/admin(.*)']);

export default clerkMiddleware(async (auth, req) => {
    if (isAuthRequired(req)) {
        await auth.protect();
    }

    const { orgId, orgRole } = await auth();

    if (isOrgRequired(req) && !orgId) {
        return Response.redirect(new URL('/select-org', req.url));
    }

    if (isAdminRoute(req) && orgRole !== 'org:admin') {
        return Response.redirect(new URL('/dashboard', req.url));
    }
});

export const config = {
    matcher: [
        '/((?!_next|.*\\.(?:html?|css|js(?!on)|png|gif|svg|ico)).*)',
        '/(api|trpc)(.*)',
    ],
};

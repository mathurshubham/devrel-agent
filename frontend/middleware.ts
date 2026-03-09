import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';

const isProtected = createRouteMatcher(['/dashboard(.*)']);
const isAdminRoute = createRouteMatcher(['/dashboard/settings(.*)', '/admin(.*)']);

export default clerkMiddleware(async (auth, req) => {
    const { orgId, orgRole } = await auth();

    if (isProtected(req)) {
        await auth.protect();

        if (!orgId) {
            return Response.redirect(new URL('/select-org', req.url));
        }
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

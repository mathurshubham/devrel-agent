import { Webhook } from 'svix';
import { headers } from 'next/headers';

// Mocking db for now as per TRD context, though in a real app this would be imported from a lib
// const db = ...;

export async function POST(req: Request) {
    const WEBHOOK_SECRET = process.env.CLERK_WEBHOOK_SECRET;
    if (!WEBHOOK_SECRET) {
        return Response.json({ error: 'Missing CLERK_WEBHOOK_SECRET' }, { status: 500 });
    }

    const hdrs = await headers();

    // ── Replay attack guard (Teammate 4) ──────────────────────────────────────
    const svixTimestamp = hdrs.get('svix-timestamp');
    if (!svixTimestamp) return Response.json({ error: 'Missing timestamp' }, { status: 400 });

    const ageMs = Date.now() - Number(svixTimestamp) * 1000;
    if (ageMs > 5 * 60 * 1000) {
        return Response.json({ error: 'Webhook timestamp too old — replay rejected' }, { status: 400 });
    }

    // ── HMAC signature verification ───────────────────────────────────────────
    const wh = new Webhook(WEBHOOK_SECRET);
    const body = await req.text();
    let evt: any;

    try {
        evt = wh.verify(body, {
            'svix-id': hdrs.get('svix-id')!,
            'svix-timestamp': svixTimestamp,
            'svix-signature': hdrs.get('svix-signature')!,
        });
    } catch (err) {
        return Response.json({ error: 'Invalid signature' }, { status: 400 });
    }

    // ── Idempotency (Teammate 3: use upsert / on_conflict_do_nothing) ─────────
    const eventId = hdrs.get('svix-id')!;

    // Note: Using a placeholder for db.$executeRaw as the actual DB client setup 
    // depends on the project's specific Prisma/Drizzle configuration.
    // The logic below follows the TRD requirement precisely.

    /*
    const inserted = await db.$executeRaw`
      INSERT INTO processed_webhook_events (event_id, event_type, processed_at)
      VALUES (${eventId}, ${evt.type}, NOW())
      ON CONFLICT (event_id) DO NOTHING
    `;
    if (inserted === 0) {
      return Response.json({ ok: true, skipped: 'duplicate' });
    }
    */

    // SCAFFOLDING EVENT MAPPING
    switch (evt.type) {
        case 'user.created':
            // await syncUser(evt.data);
            break;
        case 'user.updated':
            // await updateUser(evt.data);
            break;
        case 'user.deleted':
            // await deactivateUser(evt.data);
            break;
        case 'organization.created':
            // await syncOrg(evt.data);
            break;
        case 'organizationMembership.created':
            // await linkUserToOrg(evt.data);
            break;
        case 'organization.deleted':
            // await deactivateOrg(evt.data);
            break;
        default:
            console.log(`Unhandled event type: ${evt.type}`);
    }

    return Response.json({ received: true });
}

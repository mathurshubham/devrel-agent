# Clerk Webhook & CORS Configuration Guide

This guide details the steps required to sync Clerk authentication with the DevRel Agent backend and configure CORS for secure cross-origin communication.

## 1. Clerk Dashboard Setup

### Webhook Configuration
1. Navigate to your **Clerk Dashboard** > **Webhooks**.
2. Click **Add Endpoint**.
3. **Endpoint URL:** `https://<YOUR-TUNNEL-URL>/api/webhooks/clerk` (e.g., your ngrok or Cloudflare tunnel URL).
4. **Events to Subscribe:**
   - `user.created`
   - `user.updated`
   - `user.deleted`
   - `organization.created`
   - `organizationMembership.created`
   - `organization.deleted`
5. Click **Create**.
6. Copy the **Signing Secret**.

### Environment Variables (.env)
Update your `backend/.env` with the signing secret:
```env
CLERK_WEBHOOK_SECRET=whsec_...
CLERK_SECRET_KEY=sk_test_...
```

## 2. CORS Configuration

The backend is pre-configured with `CORSMiddleware`. Ensure the following environment variables are set to allow your frontend to communicate with the backend:

```env
NEXT_PUBLIC_FRONTEND_URL=https://your-frontend-domain.com
NEXT_PUBLIC_API_URL=https://your-backend-tunnel.com
```

### Development (ngrok/Cloudflare)
If you are testing via a tunnel, the `useApi` hook and `main.py` are configured to handle the `ngrok-skip-browser-warning` header. If using Cloudflare, ensure your tunnel allows the `Authorization` header.

## 3. Super Admin Promotion

To promote the first user to Super Admin:
1. Manually add `{"role": "SUPER_ADMIN"}` to the user's **Public Metadata** in the Clerk Dashboard.
2. Alternatively, update the `users` table in PostgreSQL directly:
   ```sql
   UPDATE users SET role = 'SUPER_ADMIN' WHERE email = 'your-email@example.com';
   ```
3. Once the first Super Admin is established, use the `/admin` dashboard in the frontend to promote others.

## 4. Verification Checklist

- [ ] Webhook pings succeed in Clerk Dashboard.
- [ ] User records appear in the `users` table after login.
- [ ] Frontend requests include `Authorization: Bearer <token>` in headers.
- [ ] `/admin` page is hidden for regular members and visible for Super Admins.

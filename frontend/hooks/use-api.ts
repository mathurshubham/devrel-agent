import axios from 'axios';
import { useAuth } from '@clerk/nextjs';
import { useMemo } from 'react';

/**
 * useApi hook
 * Provides a pre-configured axios instance with a Clerk JWT interceptor.
 * The token is fetched dynamically before every request.
 */
export const useApi = () => {
    const { getToken } = useAuth();

    const api = useMemo(() => {
        const instance = axios.create({
            // Empty string = relative URLs, which flow through the Next.js
            // rewrite proxy (see next.config.ts) honoring BACKEND_INTERNAL_URL.
            baseURL: process.env.NEXT_PUBLIC_API_URL || '',
            headers: {
                'Content-Type': 'application/json',
                // ngrok bypass header for development
                'ngrok-skip-browser-warning': 'true',
            },
        });

        instance.interceptors.request.use(async (config) => {
            try {
                const token = await getToken();
                if (token) {
                    config.headers.Authorization = `Bearer ${token}`;
                }
            } catch (error) {
                console.error('Failed to get Clerk token:', error);
            }
            return config;
        });

        return instance;
    }, [getToken]);

    return api;
};

// FastAPI error payloads are not always strings: Pydantic validation errors
// arrive as an array of objects, which must never reach a React child or a
// toast directly (React error #31 tears down the whole tree). Always funnel
// API errors through this helper.
export function apiErrorText(err: unknown, fallback = "Request failed"): string {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        const msgs = detail
            .map((d) => (typeof d === "object" && d !== null && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
            .filter(Boolean);
        if (msgs.length) return msgs.join("; ");
    }
    if (detail !== undefined && detail !== null) {
        try { return JSON.stringify(detail); } catch { /* fall through */ }
    }
    const message = (err as { message?: unknown })?.message;
    return typeof message === "string" && message ? message : fallback;
}

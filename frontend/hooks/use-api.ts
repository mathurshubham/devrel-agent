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
            baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
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

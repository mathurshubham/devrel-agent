'use client';

import { useUser } from '@clerk/nextjs';

import { useApi, apiErrorText } from '@/hooks/use-api';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ShieldCheck, Users, Building2, AlertTriangle } from 'lucide-react';

export default function AdminDashboard() {
    const { user, isLoaded } = useUser();
    const api = useApi();
    const queryClient = useQueryClient();

    // 1. RBAC Gating (TRD Section 3.6)
    const isSuperAdmin = user?.publicMetadata?.role === 'SUPER_ADMIN';

    const { data: orgs, isLoading: loadingOrgs } = useQuery({
        queryKey: ['admin-orgs'],
        queryFn: async () => {
            const resp = await api.get('/api/admin/organizations');
            return resp.data;
        },
        enabled: isSuperAdmin,
    });

    const { data: users, isLoading: loadingUsers } = useQuery({
        queryKey: ['admin-users'],
        queryFn: async () => {
            const resp = await api.get('/api/admin/users');
            return resp.data;
        },
        enabled: isSuperAdmin,
    });

    const promoteMutation = useMutation({
        mutationFn: async (targetUserId: number) => {
            return await api.post(`/api/admin/promote/${targetUserId}`);
        },
        onSuccess: () => {
            toast.success('User promoted to Super Admin successfully!');
            queryClient.invalidateQueries({ queryKey: ['admin-users'] });
        },
        onError: (error: any) => {
            if (error.response?.status === 403) {
                toast.error('403 Forbidden: You do not have permission to perform this action.');
            } else {
                toast.error(apiErrorText(error, 'Failed to promote user.'));
            }
        },
    });

    if (!isLoaded) return <div className="p-8">Loading session...</div>;

    if (!isSuperAdmin) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[60vh] p-8 text-center">
                <AlertTriangle className="w-12 h-12 text-destructive mb-4" />
                <h1 className="text-2xl font-bold mb-2">403 - Restricted Access</h1>
                <p className="text-muted-foreground">
                    This area is only accessible to Platform Super Admins.
                </p>
                <Button className="mt-6" variant="outline" onClick={() => window.location.href = '/dashboard'}>
                    Return to Dashboard
                </Button>
            </div>
        );
    }

    return (
        <div className="p-8 space-y-8 max-w-7xl mx-auto">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Super Admin Dashboard</h1>
                    <p className="text-muted-foreground">Manage platform-wide organizations and access control.</p>
                </div>
                <Badge variant="secondary" className="px-3 py-1 text-sm flex gap-2">
                    <ShieldCheck className="w-4 h-4" />
                    Super Admin Mode
                </Badge>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Organizations Table */}
                <Card className="border-zinc-800 bg-zinc-950">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Building2 className="w-5 h-5 text-blue-400" />
                            Organizations
                        </CardTitle>
                        <CardDescription>All tenants registered on the platform.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Name</TableHead>
                                    <TableHead>Clerk Org ID</TableHead>
                                    <TableHead>Status</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {loadingOrgs ? (
                                    <TableRow><TableCell colSpan={3}>Loading orgs...</TableCell></TableRow>
                                ) : orgs?.map((org: any) => (
                                    <TableRow key={org.id}>
                                        <TableCell className="font-medium">{org.name}</TableCell>
                                        <TableCell className="text-xs font-mono">{org.clerk_org_id}</TableCell>
                                        <TableCell>
                                            <Badge variant={org.is_active ? 'default' : 'destructive'}>
                                                {org.is_active ? 'Active' : 'Suspended'}
                                            </Badge>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </CardContent>
                </Card>

                {/* Users Table */}
                <Card className="border-zinc-800 bg-zinc-950">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Users className="w-5 h-5 text-emerald-400" />
                            Users & Roles
                        </CardTitle>
                        <CardDescription>Manage user roles across all organizations.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Email</TableHead>
                                    <TableHead>Role</TableHead>
                                    <TableHead className="text-right">Actions</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {loadingUsers ? (
                                    <TableRow><TableCell colSpan={3}>Loading users...</TableCell></TableRow>
                                ) : users?.map((u: any) => (
                                    <TableRow key={u.id}>
                                        <TableCell className="max-w-[150px] truncate">{u.email}</TableCell>
                                        <TableCell>
                                            <Badge variant={u.role === 'SUPER_ADMIN' ? 'secondary' : 'outline'}>
                                                {u.role}
                                            </Badge>
                                        </TableCell>
                                        <TableCell className="text-right">
                                            {u.role !== 'SUPER_ADMIN' && (
                                                <Button
                                                    size="sm"
                                                    variant="ghost"
                                                    className="text-xs h-8"
                                                    onClick={() => promoteMutation.mutate(u.id)}
                                                    disabled={promoteMutation.isPending}
                                                >
                                                    Promote
                                                </Button>
                                            )}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}

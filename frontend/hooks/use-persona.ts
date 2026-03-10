import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface OrgPersona {
    master_context?: string;
    rulesets_dos_donts?: string;
    tone_guidelines?: string;
}

export function usePersona() {
    return useQuery({
        queryKey: ["persona"],
        queryFn: async (): Promise<OrgPersona> => {
            const res = await fetch("/api/persona");
            if (!res.ok) {
                // Return an empty persona if not found, to allow initial creation
                if (res.status === 404) {
                    return { master_context: "", rulesets_dos_donts: "", tone_guidelines: "" };
                }
                throw new Error("Failed to fetch persona");
            }
            return res.json();
        },
    });
}

export function useUpdatePersona() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload: OrgPersona) => {
            const res = await fetch("/api/persona", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.detail || errorData.error || "Failed to update persona");
            }
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["persona"] });
        },
    });
}

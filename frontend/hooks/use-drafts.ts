import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

interface Draft {
    id: string;
    status: string;
    subreddit: string;
    confidence: number;
    reasoning: string[];
    post_title: string;
    original_text: string;
    ai_draft_text: string;
    model_used: string;
    prompt_version: string;
    created_at: string;
}

interface UpdateDraftPayload {
    id: string;
    status: "PUBLISHED" | "REJECTED";
    edited_text?: string;
}

export function useDrafts(searchQuery?: string) {
    return useQuery({
        queryKey: ["drafts", searchQuery],
        queryFn: async (): Promise<Draft[]> => {
            const url = searchQuery
                ? `/api/drafts?q=${encodeURIComponent(searchQuery)}`
                : '/api/drafts';
            const res = await fetch(url);
            if (!res.ok) throw new Error("Failed to fetch drafts");
            return res.json();
        },
        // Keeps the current table visible while fetching search results!
        placeholderData: (previousData) => previousData,
    });
}

export function useUpdateDraftStatus() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, status, edited_text }: UpdateDraftPayload) => {
            const payload: any = { status };
            if (edited_text !== undefined) {
                payload.edited_text = edited_text;
            }

            const res = await fetch(`/api/drafts/${id}/status`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error("Failed to update status");
            return res.json();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["drafts"] });
        }
    });
}

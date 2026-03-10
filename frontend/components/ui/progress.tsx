"use client"

import * as React from "react"
import { Progress as ProgressPrimitive } from "@base-ui/react/progress"

import { cn } from "@/lib/utils"

function Progress({
    className,
    value,
    ...props
}: ProgressPrimitive.Root.Props & { value?: number }) {
    return (
        <ProgressPrimitive.Root
            data-slot="progress"
            className={cn(
                "relative h-2 w-full overflow-hidden rounded-full bg-muted",
                className
            )}
            value={value}
            {...props}
        >
            <ProgressPrimitive.Track className="size-full">
                <ProgressPrimitive.Indicator
                    className="h-full w-full flex-1 bg-primary transition-all"
                    style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
                />
            </ProgressPrimitive.Track>
        </ProgressPrimitive.Root>
    )
}

export { Progress }

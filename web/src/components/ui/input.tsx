import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn("h-10 w-full rounded-lg border border-border bg-input px-3 text-sm outline-none transition focus:border-foreground/30", className)}
      {...props}
    />
  )
}

export { Input }

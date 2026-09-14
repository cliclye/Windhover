import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn("min-h-20 w-full resize-none rounded-xl border-0 bg-transparent px-4 py-3 text-sm leading-6 outline-none placeholder:text-muted-foreground", className)}
      {...props}
    />
  )
}

export { Textarea }

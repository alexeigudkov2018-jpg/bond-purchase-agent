import * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-xl border border-[#d9d0c2] bg-white px-3 text-sm text-[#1a1814] outline-none placeholder:text-[#8a8175] focus-visible:ring-2 focus-visible:ring-[#8d4b32]",
        className,
      )}
      {...props}
    />
  );
}

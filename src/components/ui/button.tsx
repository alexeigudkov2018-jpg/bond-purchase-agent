import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-[#8d4b32]",
  {
    variants: {
      variant: {
        default: "bg-[#1a1814] text-[#f6f1e7] hover:bg-[#3a332c]",
        copper: "bg-[#8d4b32] text-[#fffaf3] hover:bg-[#733c28]",
        outline: "border border-[#d9d0c2] bg-transparent hover:bg-[#f6f1e7]",
        ghost: "hover:bg-[#efe8dc]",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-xs",
        lg: "h-12 px-6",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

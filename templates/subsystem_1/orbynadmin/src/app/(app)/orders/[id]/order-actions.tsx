"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  IconPencil,
  IconDownload,
  IconDotsVertical,
  IconCopy,
  IconMail,
  IconCopyPlus,
  IconTrash,
} from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DeleteDialog } from "@/components/delete-dialog";

export function OrderActions({
  slug,
  orderId,
  customerEmail,
}: {
  slug: string;
  orderId: string;
  customerEmail: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" asChild>
        <Link href={`/orders/${slug}/edit`}>
          <IconPencil className="size-4" /> Edit
        </Link>
      </Button>

      <Button
        variant="outline"
        onClick={() =>
          toast.success(`Invoice for ${orderId} downloaded`, {
            description: "Your PDF will be ready in a moment.",
          })
        }
      >
        <IconDownload className="size-4" /> Download invoice
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="icon" className="size-9">
            <IconDotsVertical className="size-4" />
            <span className="sr-only">More actions</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem
            onClick={() => {
              navigator.clipboard?.writeText(orderId);
              toast.success("Order ID copied", { description: orderId });
            }}
          >
            <IconCopy className="size-4" /> Copy order ID
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <a href={`mailto:${customerEmail}`}>
              <IconMail className="size-4" /> Email customer
            </a>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              toast.success("Order duplicated", {
                description: `A draft copy of ${orderId} was created.`,
              })
            }
          >
            <IconCopyPlus className="size-4" /> Duplicate order
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onClick={() => setOpen(true)}>
            <IconTrash className="size-4" /> Delete order
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DeleteDialog
        open={open}
        onOpenChange={setOpen}
        name={orderId}
        description={`This will permanently remove order ${orderId} and its line items. This action cannot be undone.`}
        onConfirm={() => router.push("/orders")}
      />
    </div>
  );
}

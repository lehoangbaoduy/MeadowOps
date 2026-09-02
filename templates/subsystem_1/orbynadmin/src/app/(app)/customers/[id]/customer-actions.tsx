"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  IconPencil,
  IconDotsVertical,
  IconMail,
  IconCopy,
  IconArchive,
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

export function CustomerActions({
  id,
  name,
  email,
}: {
  id: string;
  name: string;
  email: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button variant="outline" asChild>
        <Link href={`/customers/${id}/edit`}>
          <IconPencil className="size-4" /> Edit
        </Link>
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="icon" className="size-9">
            <IconDotsVertical className="size-4" />
            <span className="sr-only">More actions</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuItem asChild>
            <a href={`mailto:${email}`}>
              <IconMail className="size-4" /> Send email
            </a>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              navigator.clipboard?.writeText(id);
              toast.success("Customer ID copied", { description: id });
            }}
          >
            <IconCopy className="size-4" /> Copy ID
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              toast.success("Customer archived", {
                description: `${name} moved to the archive.`,
              })
            }
          >
            <IconArchive className="size-4" /> Archive
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onClick={() => setOpen(true)}>
            <IconTrash className="size-4" /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DeleteDialog
        open={open}
        onOpenChange={setOpen}
        name={name}
        description={`This will permanently remove ${name} and all associated orders and activity. This action cannot be undone.`}
        onConfirm={() => router.push("/customers")}
      />
    </>
  );
}

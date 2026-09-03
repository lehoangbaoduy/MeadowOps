import type { Metadata } from "next"
import { NotFoundError } from "./components/not-found-error"

export const metadata: Metadata = {
  title: "Page not found - MeadowOps",
}

export default function NotFoundPage() {
  return <NotFoundError />
}

/** What the account menu calls the signed-in user. The Admin role is the Builder. */
export function roleLabel(role: string | null | undefined): string {
  if (role === "admin") return "Builder";
  if (role === "analyst") return "Analyst";
  return "User";
}

export function roleDetail(role: string | null | undefined): string {
  if (role === "admin") return "Admin account";
  if (role === "analyst") return "Analyst account";
  return "Signed in";
}

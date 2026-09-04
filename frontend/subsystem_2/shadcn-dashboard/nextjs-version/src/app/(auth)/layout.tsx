import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign in - MeadowOps",
  description: "Builder (admin) access to the MeadowOps scenario workspace.",
};

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background">
      {children}
    </div>
  );
}

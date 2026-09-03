import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign in - MeadowOps",
  description: "Analyst access to the MeadowOps work simulation engine.",
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

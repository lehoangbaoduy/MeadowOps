"use client"

import { Button } from "@/components/ui/button"
import { useRouter } from "next/navigation"

export function NotFoundError() {
  const router = useRouter()

  return (
    <div className='mx-auto flex min-h-dvh flex-col items-center justify-center gap-8 p-8 md:gap-12 md:p-16'>
      <div className='text-center'>
        <h1 className='mb-4 text-3xl font-bold'>404</h1>
        <h2 className="mb-3 text-2xl font-semibold">Page Not Found</h2>
        <p>The page you are looking for doesn&apos;t exist or has been moved to another location.</p>
        <div className='mt-6 flex items-center justify-center gap-4 md:mt-8'>
          <Button className='cursor-pointer' onClick={() => router.push('/dashboard')}>Go Back Home</Button>
        </div>
      </div>
    </div>
  )
}

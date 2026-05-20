"use client"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import Link from "next/link"

function VerifyInner() {
  const params = useSearchParams()
  const email = params.get("email") || "your inbox"
  return (
    <div>
      <h1 className="font-display text-2xl font-semibold mb-2">Check your email</h1>
      <p className="text-sm text-text-muted mb-6">
        We sent a verification link to <span className="text-text">{email}</span>. Click it to finish signing up.
      </p>
      <div className="rounded-lg border border-border bg-surface p-4 text-xs text-text-muted">
        Didn&apos;t get it within a minute? Check spam, or{" "}
        <Link href="/signup" className="text-gold hover:underline">try a different email</Link>.
      </div>
    </div>
  )
}

export default function VerifyPage() {
  return <Suspense fallback={null}><VerifyInner /></Suspense>
}

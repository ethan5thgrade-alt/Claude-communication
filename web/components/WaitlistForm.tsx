'use client'

import { useState } from 'react'

interface WaitlistFormProps {
  source?: string
  onSuccess?: () => void
}

export function WaitlistForm({ source = 'landing', onSuccess }: WaitlistFormProps) {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setMessage(null)

    try {
      const response = await fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, source }),
      })

      const data = await response.json()

      if (!response.ok) {
        setMessage({
          type: 'error',
          text: data.error === 'Email already on waitlist'
            ? 'You\'re already on the waitlist!'
            : data.error || 'Failed to join waitlist',
        })
        return
      }

      setMessage({
        type: 'success',
        text: 'Check your email for next steps.',
      })
      setEmail('')
      onSuccess?.()
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Something went wrong. Please try again.',
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="flex flex-col sm:flex-row gap-2">
        <input
          type="email"
          placeholder="your@email.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={loading}
          required
          className="flex-1 rounded-sm bg-surface border border-border px-4 py-3 text-sm placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-gold disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-sm bg-gold px-6 py-3 text-sm font-medium text-bg hover:opacity-95 transition-opacity disabled:opacity-50"
        >
          {loading ? 'Joining...' : 'Join waitlist'}
        </button>
      </div>
      {message && (
        <p className={`text-xs ${message.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>
          {message.text}
        </p>
      )}
    </form>
  )
}

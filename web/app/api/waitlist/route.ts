import { createClient } from '@supabase/supabase-js'
import { NextRequest, NextResponse } from 'next/server'

export async function POST(request: NextRequest) {
  // Client is created per-request, not at module scope: a module-scope
  // createClient crashes the build when env vars are absent (page-data collection).
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  if (!url || !key) {
    return NextResponse.json({ error: 'Waitlist not configured' }, { status: 503 })
  }
  const supabase = createClient(url, key)

  try {
    const { email, source: rawSource } = await request.json()
    // Must match the table's CHECK constraint or the insert 500s.
    const ALLOWED_SOURCES = ['landing', 'demo', 'community']
    const source = ALLOWED_SOURCES.includes(rawSource) ? rawSource : 'landing'

    if (!email || typeof email !== 'string') {
      return NextResponse.json(
        { error: 'Email is required' },
        { status: 400 }
      )
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailRegex.test(email)) {
      return NextResponse.json(
        { error: 'Invalid email address' },
        { status: 400 }
      )
    }

    // No .select() after insert: the anon RLS policy allows INSERT only, so a
    // RETURNING clause would be blocked and fail the whole request.
    const { error } = await supabase
      .from('waitlist')
      .insert([{ email, source }])

    if (error) {
      if (error.code === '23505') {
        return NextResponse.json(
          { error: 'Email already on waitlist' },
          { status: 409 }
        )
      }
      throw error
    }

    return NextResponse.json({ success: true }, { status: 201 })
  } catch (error) {
    console.error('Waitlist error:', error)
    return NextResponse.json(
      { error: 'Failed to add to waitlist' },
      { status: 500 }
    )
  }
}

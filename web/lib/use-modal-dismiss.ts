"use client"
import { useEffect, useRef } from "react"

// Modal a11y. Attaching an Escape handler to the dialog element only fires when
// focus already sits inside the modal, so a dialog that does not move focus on
// open (e.g. a details modal opened from a background button) never closes on
// Escape. Listen on document instead, and manage focus: move it into the dialog
// on open and restore it to the trigger on close.
//
// Returns a ref to attach to the dialog container (give it tabIndex={-1} so it
// can receive focus).
export function useModalDismiss<T extends HTMLElement>(onClose: () => void) {
  const ref = useRef<T>(null)
  // Keep the latest onClose without re-running the effect (callers usually pass
  // a fresh closure each render).
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation()
        onCloseRef.current()
      }
    }
    document.addEventListener("keydown", onKey)
    // Pull focus into the dialog only if nothing inside it is focused yet, so an
    // autoFocus child (e.g. the first input) keeps focus.
    if (ref.current && !ref.current.contains(document.activeElement)) {
      ref.current.focus()
    }
    return () => {
      document.removeEventListener("keydown", onKey)
      previouslyFocused?.focus?.()
    }
  }, [])

  return ref
}

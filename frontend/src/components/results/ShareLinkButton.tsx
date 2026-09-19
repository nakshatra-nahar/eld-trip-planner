import { Check, Link2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '../ui'

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    return
  } catch {
    // Clipboard API blocked (insecure context, permissions): fall back to a hidden textarea.
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  const ok = document.execCommand('copy')
  area.remove()
  if (!ok) throw new Error('copy failed')
}

/** Copies a link that reopens this exact plan (see lib/planQuery). */
export function ShareLinkButton({ url }: { url: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')

  useEffect(() => {
    if (state === 'idle') return
    const id = window.setTimeout(() => setState('idle'), 2200)
    return () => window.clearTimeout(id)
  }, [state])

  return (
    <>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => copyText(url).then(() => setState('copied'), () => setState('failed'))}
        icon={state === 'copied' ? <Check className="size-3.5 text-duty-d" aria-hidden /> : <Link2 className="size-3.5" aria-hidden />}
        title={url}
      >
        {state === 'copied' ? 'Link copied' : state === 'failed' ? 'Copy failed' : 'Copy share link'}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === 'copied' ? 'Share link copied to the clipboard.' : state === 'failed' ? 'Could not copy the link.' : ''}
      </span>
    </>
  )
}

// Client-side export of a rendered log sheet: standalone SVG file or 2x PNG.

import { SHEET } from './geometry'

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Give the browser a tick to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** The sheet's ink face (see INK_FONT in LogSheet.tsx), latin subset only. */
const FONT_CSS_URL = 'https://fonts.googleapis.com/css2?family=Geist+Mono:wght@500;600;700&display=swap'

let fontCss: Promise<string> | null = null

function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/**
 * @font-face rules with the font files inlined as data: URLs. An SVG rendered through an
 * <img> (PNG export) or opened on another machine cannot load the page's web fonts, so
 * without this the ink text falls back to a system monospace. Best effort: offline, the
 * export still works with the fallback font.
 */
function embeddedFontCss(): Promise<string> {
  fontCss ??= (async () => {
    const css = await (await fetch(FONT_CSS_URL)).text()
    const latin = css
      .split('/* ')
      .filter((block) => block.startsWith('latin */'))
      .map((block) => block.slice('latin */'.length))
      .join('\n')
    const urls = [...new Set([...latin.matchAll(/url\((https:[^)]+)\)/g)].map((m) => m[1]))]
    let out = latin
    for (const url of urls) {
      const data = await toDataUrl(await (await fetch(url)).blob())
      out = out.split(url).join(data)
    }
    return out
  })().catch(() => {
    fontCss = null
    return ''
  })
  return fontCss
}

/** Serialize the sheet as a standalone SVG document with explicit pixel size and embedded fonts. */
export async function serializeSheet(svg: SVGSVGElement): Promise<string> {
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(SHEET.width))
  clone.setAttribute('height', String(SHEET.height))
  clone.removeAttribute('class')
  clone.removeAttribute('style')
  // Screen-only decoration (duty-colour row wash) never goes into a download.
  clone.querySelectorAll('[data-screen-only]').forEach((el) => el.remove())
  const css = await embeddedFontCss()
  if (css) {
    const style = document.createElementNS('http://www.w3.org/2000/svg', 'style')
    style.textContent = css
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs')
    defs.appendChild(style)
    clone.insertBefore(defs, clone.firstChild)
  }
  const xml = new XMLSerializer().serializeToString(clone)
  return `<?xml version="1.0" encoding="UTF-8"?>\n${xml}`
}

export async function downloadSvg(svg: SVGSVGElement, filename: string) {
  triggerDownload(new Blob([await serializeSheet(svg)], { type: 'image/svg+xml;charset=utf-8' }), filename)
}

/** Rasterize via an <img> + canvas at `scale`x the viewBox size. */
export async function downloadPng(svg: SVGSVGElement, filename: string, scale = 2) {
  const svgUrl = URL.createObjectURL(new Blob([await serializeSheet(svg)], { type: 'image/svg+xml;charset=utf-8' }))
  try {
    const img = new Image()
    img.decoding = 'async'
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error('Could not rasterize the log sheet'))
      img.src = svgUrl
    })
    const canvas = document.createElement('canvas')
    canvas.width = SHEET.width * scale
    canvas.height = SHEET.height * scale
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas 2D is not available')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('PNG encoding failed')
    triggerDownload(blob, filename)
  } finally {
    URL.revokeObjectURL(svgUrl)
  }
}

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

/** Serialize the sheet as a standalone SVG document with explicit pixel size. */
export function serializeSheet(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(SHEET.width))
  clone.setAttribute('height', String(SHEET.height))
  clone.removeAttribute('class')
  clone.removeAttribute('style')
  const xml = new XMLSerializer().serializeToString(clone)
  return `<?xml version="1.0" encoding="UTF-8"?>\n${xml}`
}

export function downloadSvg(svg: SVGSVGElement, filename: string) {
  triggerDownload(new Blob([serializeSheet(svg)], { type: 'image/svg+xml;charset=utf-8' }), filename)
}

/** Rasterize via an <img> + canvas at `scale`x the viewBox size. */
export async function downloadPng(svg: SVGSVGElement, filename: string, scale = 2) {
  const svgUrl = URL.createObjectURL(new Blob([serializeSheet(svg)], { type: 'image/svg+xml;charset=utf-8' }))
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

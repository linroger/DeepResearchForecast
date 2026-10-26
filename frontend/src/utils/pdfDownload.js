/** Fetch and validate before creating a browser download. Never save error pages. */
export async function downloadPdf(url, { filename, signal, isCurrent = () => true }) {
  const current = () => !signal?.aborted && isCurrent()
  const response = await fetch(url, { signal, headers: { Accept: 'application/pdf' } })
  if (!current()) return false
  if (!response.ok) {
    let detail = ''
    if (/application\/json/i.test(response.headers.get('content-type') || '')) {
      try {
        const body = await response.json()
        const message = body.error?.message || body.error || body.message
        if (typeof message === 'string') detail = message.slice(0, 300)
        if (!detail) detail = {
          pdf_export_disabled: 'PDF export is disabled on the server.',
          pdf_render_failed: 'The server could not render this PDF. Please retry.',
          pdf_invalid: 'The server returned an invalid PDF file.',
          pdf_internal_error: 'PDF export failed on the server. Please retry.',
          source_changed: 'The source changed. Reload the dossier before exporting.',
          generation_changed: 'The translation changed. Check its status before exporting.',
        }[body.code] || ''
      } catch { /* A malformed error body must not hide the HTTP failure. */ }
    }
    throw new Error(detail || `PDF download failed (HTTP ${response.status}).`)
  }
  if (!/^application\/pdf(?:\s*;|\s*$)/i.test(response.headers.get('content-type') || '')) {
    throw new Error('The server did not return a PDF (invalid content type).')
  }
  const blob = await response.blob()
  const magic = await blob.slice(0, 5).text()
  if (!current()) return false
  if (magic !== '%PDF-') throw new Error('The server returned an invalid PDF file.')
  const objectUrl = URL.createObjectURL(blob)
  let anchor
  try {
    anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
  } finally {
    anchor?.remove()
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  }
  return true
}

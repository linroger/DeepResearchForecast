/**
 * Hand the browser a text file to save (CSV exports of stored official data).
 * The object URL is revoked on the next tick, after the click has been dispatched.
 * @param {string} text
 * @param {string} filename
 * @param {string} type - MIME type, e.g. 'text/csv;charset=utf-8'
 */
export function saveTextFile(text, filename, type) {
  const objectUrl = URL.createObjectURL(new Blob([text], { type }))
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
}

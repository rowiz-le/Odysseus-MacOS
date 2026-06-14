/**
 * Open a Deep Research report without creating a navigation-less pywebview
 * window. Regular browsers still get a separate tab.
 */
export function openResearchReport(url) {
  const target = new URL(url, window.location.origin).href;

  if (window.pywebview?.api) {
    window.location.assign(target);
    return;
  }

  const opened = window.open(target, '_blank');
  if (opened) {
    try { opened.opener = null; } catch {}
    return;
  }
  window.location.assign(target);
}

export default { openResearchReport };

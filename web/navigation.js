// Viewer state stays in the browser. Explicit links take precedence on entry.
export const LAST_VIEW_KEY = 'filletbench-last-benchmark-view-v1';
const SERIES = new Set(['original', 'comparison']);

export function normaliseView(value) {
  if (!value || !SERIES.has(value.series)) return null;
  const number = String(value.case ?? '');
  if (!/^\d{1,2}$/.test(number) || Number(number) < 1) return null;
  const variant = typeof value.variant === 'string' && value.variant.length <= 180 ? value.variant : null;
  return { series: value.series, case: number.padStart(2, '0'), variant: variant || null };
}

export function routeFromURL(href) {
  const hash = new URL(href).hash.slice(1);
  if (!hash) return null;
  if (hash.includes('=')) {
    const params = new URLSearchParams(hash);
    if (!params.has('case') && !params.has('variant') && !params.has('series')) return null;
    return { series: SERIES.has(params.get('series')) ? params.get('series') : 'original',
      case: params.get('case'), variant: params.get('variant'), explicitSeries: params.has('series') };
  }
  const match = /^(?:(history)\/)?(\d{1,2})(?:\/(.+))?$/.exec(hash);
  if (!match) return null;
  let variant = null;
  try { variant = match[3] ? decodeURIComponent(match[3]) : null; } catch { return null; }
  const view = normaliseView({ series: match[1] ? 'comparison' : 'original', case: match[2], variant });
  return view ? { ...view, explicitSeries: true } : null;
}

export function cleanViewerURL(href) {
  const url = new URL(href);
  url.search = ''; url.hash = '';
  url.pathname = url.pathname.replace(/index\.html$/, '');
  return url.href;
}

export function shareViewerURL(href, value) {
  const view = normaliseView(value);
  if (!view) throw new Error('No current case to share');
  const url = new URL(cleanViewerURL(href));
  url.hash = `${view.series === 'comparison' ? 'history/' : ''}${view.case}${view.variant ? '/' + encodeURIComponent(view.variant) : ''}`;
  return url.href;
}

export function initialView(href, historyState, storedView) {
  return routeFromURL(href) || normaliseView(historyState?.filletbenchView) ||
    normaliseView(storedView) || { series: 'original', case: null, variant: null, explicitSeries: true };
}

export function rememberView(browser, value) {
  const view = normaliseView(value);
  if (!view) return;
  const previous = browser.history.state;
  browser.history.replaceState({ ...(previous && typeof previous === 'object' ? previous : {}), filletbenchView: view }, '', cleanViewerURL(browser.location.href));
  // A new visit to the main entry resumes a benchmark, not an archived experiment.
  if (view.series === 'original') {
    try { browser.localStorage.setItem(LAST_VIEW_KEY, JSON.stringify(view)); } catch { /* History state still supports refresh. */ }
  }
}

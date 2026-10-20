/** Read a widget-specific capability without retaining it in URLs or referrers. */
export function widgetToken(kind) {
  const key = `ddl-${kind}-widget-token`;
  const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem(key);
  if (token) sessionStorage.setItem(key, token);
  history.replaceState(null, '', location.pathname + location.search);
  return token;
}

/** Both DDL components receive only appearance from their AIRI parent. */
export function connectAppearance() {
  document.documentElement.classList.toggle('dark', matchMedia('(prefers-color-scheme:dark)').matches);
  window.addEventListener('message', event => {
    if (event.source !== parent || event.data?.type !== 'ddl-widget-appearance') return;
    document.documentElement.classList.toggle('dark', event.data.dark === true);
    if (Number.isFinite(event.data.hue) && event.data.hue >= 0 && event.data.hue <= 360)
      document.documentElement.style.setProperty('--hue', event.data.hue);
  });
}

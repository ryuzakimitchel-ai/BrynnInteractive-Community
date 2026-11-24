(() => {
  const params = new URLSearchParams(location.search);
  const allowed = new Set(['neon','spooky','day','cyber','amber','violet','mono','graphite','ocean','rose','crimson','sakura','candy','arcade','matrix','sunset','ice','coffee']);
  const theme = allowed.has(params.get('theme')) ? params.get('theme') : 'neon';
  const hex = /^#[0-9a-fA-F]{6}$/;
  const accent = params.get('accent') || '';
  const accent2 = params.get('accent2') || '';
  const density = ['compact','comfortable','spacious'].includes(params.get('density'))
    ? params.get('density')
    : 'comfortable';
  const font = (params.get('font') || '').trim();
  const radiusRaw = Number(params.get('radius'));
  const radius = Number.isFinite(radiusRaw) ? Math.max(0, Math.min(28, radiusRaw)) : 16;

  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.density = density;

  if (hex.test(accent)) {
    document.documentElement.style.setProperty('--accent', accent);
    document.documentElement.style.setProperty('--line', `color-mix(in srgb, ${accent} 22%, transparent)`);
  }
  if (hex.test(accent2)) {
    document.documentElement.style.setProperty('--accent-2', accent2);
    document.documentElement.style.setProperty('--line-2', `color-mix(in srgb, ${accent2} 24%, transparent)`);
  }
  if (font && font.length <= 64 && !/[;{}<>]/.test(font)) {
    document.documentElement.style.setProperty('--ui-font', JSON.stringify(font));
  }
  document.documentElement.style.setProperty('--ui-radius', `${radius}px`);
})();

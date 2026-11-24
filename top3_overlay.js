const cardsEl = document.getElementById("cards");
const periodEl = document.getElementById("period");

function esc(value) {
    return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
function roleLabel(rank) {
    if (rank === 1) return "VIEWER DE LA SEMANA";
    if (rank === 2) return "GUMPITA DESTACADA";
    if (rank === 3) return "GUMPITA DESTACADA";
    return "TOP";
}
function roleIcon(rank) {
    if (rank === 1) return "👑";
    if (rank === 2) return "🥈";
    if (rank === 3) return "🥉";
    return "✦";
}
function platformLabel(platform) {
    if (platform === "twitch") return "TWITCH";
    if (platform === "tiktok") return "TIKTOK";
    return (platform || "-").toUpperCase();
}
function avatarSrc(user) {
    if (user && user.avatar) return user.avatar;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#8CFF3A"/><stop offset="1" stop-color="#8A2BE2"/></linearGradient></defs><rect width="128" height="128" rx="20" fill="#17111c"/><circle cx="64" cy="48" r="22" fill="url(#g)"/><path d="M28 108c6-19 24-30 36-30s30 11 36 30" fill="url(#g)"/></svg>`;
    return "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
}
function cardHtml(user, index) {
    const rank = index + 1;
    const c = user.counters || {};
    return `<article class="card rank-${rank}">
        <div class="avatar-wrap">
            <img class="avatar" src="${avatarSrc(user)}" alt="${esc(user.username)}">
        </div>
        <div class="info">
            <div class="badge-row">
                <span class="rank-badge">${roleIcon(rank)} ${roleLabel(rank)}</span>
                <span class="platform">${platformLabel(user.platform)}</span>
            </div>
            <div class="username">${esc(user.username)}</div>
            <div class="meta">
                <span><strong>${c.messages || 0}</strong> msgs</span>
                <span><strong>${c.likes || 0}</strong> likes</span>
                <span><strong>${c.gifts || 0}</strong> regalos</span>
            </div>
        </div>
        <div class="score">
            <div class="value">${Number(user.score || 0).toFixed(1)}</div>
            <div class="label">PUNTOS</div>
        </div>
    </article>`;
}
function render(data) {
    periodEl.textContent = data.period ? ("Semana desde " + data.period) : "Sin periodo";
    const top = Array.isArray(data.top) ? data.top : [];
    if (!top.length) {
        cardsEl.innerHTML = `<div class="empty">Aún no hay interacción suficiente para mostrar el Top 3.</div>`;
        return;
    }
    cardsEl.innerHTML = top.slice(0, 3).map(cardHtml).join("");
}
async function refresh() {
    try {
        const response = await fetch("/api/ranking", { cache: "no-store" });
        if (!response.ok) throw new Error("HTTP " + response.status);
        render(await response.json());
    } catch (error) {
        cardsEl.innerHTML = `<div class="empty">No se pudo cargar el ranking local.</div>`;
        console.error(error);
    }
}
refresh();
setInterval(refresh, 5000);

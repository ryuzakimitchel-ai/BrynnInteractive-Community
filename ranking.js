const periodEl = document.getElementById("period");
const podiumEl = document.getElementById("podium");
const bodyEl = document.getElementById("ranking-body");
const resetButton = document.getElementById("reset-button");
const searchInput = document.getElementById("ranking-search");
const platformFilter = document.getElementById("platform-filter");
const clearSearch = document.getElementById("clear-search");
const searchInfo = document.getElementById("search-result-info");
const userDetail = document.getElementById("user-detail");

let latestData = null;
let selectedUserKey = "";
let weeklyRewardsByKey = {};

function esc(value) {
    return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function platformLabel(value) {
    if (value === "twitch") return "Twitch";
    if (value === "tiktok") return "TikTok";
    if (value === "kick") return "Kick";
    return value || "-";
}

function normalizeSearch(value) {
    return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/^@+/, "")
        .replace(/[\s_\-.]+/g, "");
}

function userKey(user) {
    return `${user.platform || ""}:${String(user.username || "").toLowerCase()}`;
}

function matchesSearch(user, query, platform) {
    if (platform !== "all" && user.platform !== platform) return false;
    if (!query) return true;

    const c = user.counters || {};
    const compactName = normalizeSearch(user.username);
    const rawName = String(user.username || "").toLowerCase();
    const haystack = normalizeSearch([
        user.username,
        user.platform,
        user.rank,
        user.score,
        c.messages,
        c.likes,
        c.gifts,
        c.giftCoins,
        c.donationUsd,
        c.follows,
        c.subscriptions
    ].join(" "));

    return compactName.includes(query) || rawName.includes(query) || haystack.includes(query);
}

function renderPodium(data) {
    const top = Array.isArray(data.top) ? data.top : [];
    const icons = ["👑", "🥈", "🥉"];
    const labels = ["Viewer de la semana", "Gumpita destacada", "Gumpita destacada"];

    podiumEl.innerHTML = [0, 1, 2].map(function (index) {
        const user = top[index];
        if (!user) {
            return `<article class="card"><div class="rank">${icons[index]}</div><div class="name">Sin puesto todavía</div><div class="score">${labels[index]}</div></article>`;
        }
        return `<article class="card"><div class="rank">${icons[index]}</div><div class="name">${esc(user.username)}</div><div class="score">${labels[index]} · ${platformLabel(user.platform)} · ${Number(user.score || 0).toFixed(1)} pts</div></article>`;
    }).join("");
}

function detailHtml(user) {
    const c = user.counters || {};
    const reward = weeklyRewardsByKey[user.key || userKey(user)] || null;
    const rewardHtml = reward ? `<div class="weekly-detail-badge" style="--weekly-accent:${esc(reward.accent||'#53e6ff')}">${esc(reward.badgeIcon||'✦')} ${esc(reward.badgeLabel||reward.title||reward.tier)}</div>` : '';
    return `<div class="detail-head"><div><span class="detail-platform">${esc(platformLabel(user.platform))}</span><h2>${esc(user.username)}</h2><p>Puesto #${user.rank} · ${Number(user.score || 0).toFixed(1)} puntos</p>${rewardHtml}</div><button id="close-detail" type="button">Cerrar</button></div>
      <div class="detail-stats">
        <span><b>${c.messages || 0}</b>Mensajes</span>
        <span><b>${c.likes || 0}</b>Likes</span>
        <span><b>${c.gifts || 0}</b>Regalos</span>
        <span><b>${c.giftCoins || 0}</b>Monedas</span>
        <span><b>${Number(c.donationUsd || 0).toFixed(2)}</b>USD</span>
        <span><b>${c.follows || 0}</b>Follows</span>
        <span><b>${c.subscriptions || 0}</b>Subs</span>
      </div>`;
}

function showUserDetail(user) {
    if (!user) {
        userDetail.hidden = true;
        selectedUserKey = "";
        return;
    }
    selectedUserKey = userKey(user);
    userDetail.innerHTML = detailHtml(user);
    userDetail.hidden = false;
    userDetail.querySelector("#close-detail")?.addEventListener("click", () => showUserDetail(null));
}

function filteredRanking(data) {
    const ranking = Array.isArray(data.ranking) ? data.ranking : [];
    const query = normalizeSearch(searchInput.value);
    const platform = platformFilter.value || "all";
    return ranking.filter(user => matchesSearch(user, query, platform));
}

function renderTable(data) {
    const all = Array.isArray(data.ranking) ? data.ranking : [];
    const ranking = filteredRanking(data);
    const queryText = searchInput.value.trim();

    if (queryText || platformFilter.value !== "all") {
        searchInfo.textContent = `${ranking.length} resultado${ranking.length === 1 ? "" : "s"} de ${all.length} usuarios.`;
    } else {
        searchInfo.textContent = `Mostrando ${all.length} usuario${all.length === 1 ? "" : "s"}.`;
    }

    if (!ranking.length) {
        bodyEl.innerHTML = `<tr><td colspan="11" class="empty-search">No se encontró ningún usuario con ese criterio.</td></tr>`;
        showUserDetail(null);
        return;
    }

    bodyEl.innerHTML = ranking.map(function (user) {
        const c = user.counters || {};
        const reward = weeklyRewardsByKey[user.key || userKey(user)] || null;
        const rewardBadge = reward ? `<span class="weekly-mini-badge" style="--weekly-accent:${esc(reward.accent||'#53e6ff')}">${esc(reward.badgeLabel||reward.title||reward.tier)}</span>` : '';
        return `<tr class="ranking-row ${selectedUserKey === userKey(user) ? "selected" : ""}" data-key="${esc(userKey(user))}">
            <td>${user.rank}</td><td><button class="user-link" type="button">${esc(user.username)}</button>${rewardBadge}</td><td>${platformLabel(user.platform)}</td><td>${Number(user.score || 0).toFixed(1)}</td><td>${c.messages || 0}</td><td>${c.likes || 0}</td><td>${c.gifts || 0}</td><td>${c.giftCoins || 0}</td><td>${Number(c.donationUsd || 0).toFixed(2)}</td><td>${c.follows || 0}</td><td>${c.subscriptions || 0}</td>
        </tr>`;
    }).join("");

    bodyEl.querySelectorAll(".ranking-row").forEach(row => {
        row.addEventListener("click", () => {
            const user = ranking.find(x => userKey(x) === row.dataset.key);
            showUserDetail(user);
            renderTable(data);
        });
    });

    if (ranking.length === 1 && (queryText || platformFilter.value !== "all")) {
        showUserDetail(ranking[0]);
    } else if (selectedUserKey) {
        const selected = all.find(x => userKey(x) === selectedUserKey);
        if (selected) showUserDetail(selected);
    }
}

function render(data) {
    latestData = data;
    periodEl.textContent = "Semana iniciada el " + (data.period || "-");
    renderPodium(data);
    renderTable(data);
}

function rerenderSearch() {
    if (latestData) renderTable(latestData);
}

searchInput.addEventListener("input", rerenderSearch);
platformFilter.addEventListener("change", rerenderSearch);
clearSearch.addEventListener("click", () => {
    searchInput.value = "";
    platformFilter.value = "all";
    showUserDetail(null);
    rerenderSearch();
    searchInput.focus();
});

async function refresh() {
    try {
        const [response, rewardsResponse] = await Promise.all([
            fetch("/api/ranking", { cache: "no-store" }),
            fetch("/api/weekly-rewards/active", { cache: "no-store" })
        ]);
        if (!response.ok) throw new Error("HTTP " + response.status);
        if (rewardsResponse.ok) {
            const rewards = await rewardsResponse.json();
            weeklyRewardsByKey = rewards.winnersByKey || {};
        }
        render(await response.json());
    } catch (error) {
        periodEl.textContent = "No se pudo conectar con el servidor local.";
        console.error(error);
    }
}

resetButton.addEventListener("click", async function () {
    const accepted = window.confirm("¿Seguro que quieres reiniciar el ranking de esta semana?");
    if (!accepted) return;
    const response = await fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (response.ok) render(await response.json());
});

refresh();
setInterval(refresh, 2000);

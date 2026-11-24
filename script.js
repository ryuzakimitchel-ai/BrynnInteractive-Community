/* =========================================================
   CHAT UNIFICADO V5
   + Ranking local automático semanal
========================================================= */

/* ================= CONFIGURACIÓN ================= */

const SESSION_ID_MANUAL = "PON_AQUI_TU_SESSION_ID";
const SESSION_PASSWORD_MANUAL = "false";
const DEBUG_VISIBLE = false;

let SOCIAL_STREAM_RUNTIME = {
    sessionId: "",
    password: "false"
};

async function loadSocialStreamRuntime() {
    try {
        const response = await fetch(
            "/api/social-stream-config",
            { cache: "no-store" }
        );

        const data = await response.json();

        SOCIAL_STREAM_RUNTIME.sessionId = String(
            data.sessionId || ""
        ).trim();

        SOCIAL_STREAM_RUNTIME.password = String(
            data.password || "false"
        ).trim() || "false";
    }
    catch (error) {
        console.warn(
            "No se pudo cargar configuración Social Stream Ninja:",
            error
        );
    }
}

/*
  V17: respaldo directo para eventos TikTok mediante TikFinity Desktop.
  TikFinity expone un WebSocket local en ws://localhost:21213/.
  Lo usamos sólo para follow/sub/regalo, para no duplicar el chat.
*/
const TIKFINITY_FALLBACK_ENABLED = false;
const TIKFINITY_WS_URL = "ws://localhost:21213/";

let DIRECT_INTEGRATIONS = {
    streamlabs: false,
    tikfinity: false,
    tikfinityRankLikes: false
};


/* ================= RECOMPENSAS SEMANALES ================= */

let WEEKLY_REWARDS = {
    active: false,
    winners: [],
    winnersByKey: {}
};

const weeklyEntranceChecked = new Set();

async function loadWeeklyRewards() {
    try {
        const response = await fetch(
            "/api/weekly-rewards/active",
            { cache: "no-store" }
        );
        if (!response.ok) return;
        const data = await response.json();
        WEEKLY_REWARDS = {
            active: Boolean(data.active),
            winners: Array.isArray(data.winners) ? data.winners : [],
            winnersByKey: data.winnersByKey || {}
        };
    }
    catch (error) {
        console.warn("No se pudieron cargar recompensas semanales:", error);
    }
}

function weeklyRewardFor(data) {
    const key = userKey(data);
    if (!key || !WEEKLY_REWARDS.active) return null;
    return WEEKLY_REWARDS.winnersByKey[key] || null;
}

function mountWeeklyBadge(host,reward) {
    if (!host || !reward) return;
    const html=String(reward.badgeHtml||'').trim();
    const css=String(reward.badgeCss||'');
    if(!html){host.textContent=reward.badgeIcon||'✦';return;}
    try{
        const root=host.shadowRoot||host.attachShadow({mode:'open'});
        root.innerHTML=`<style>:host{display:inline-flex;align-items:center;justify-content:center;--accent:${String(reward.accent||'#53E6FF')}}*{box-sizing:border-box}${css}</style>${html}`;
    }catch(error){host.textContent=reward.badgeIcon||'✦';}
}

function hydrateWeeklyBadgeHosts(root,reward){
    if(!root||!reward)return;
    root.querySelectorAll('.weekly-custom-badge-host').forEach(host=>mountWeeklyBadge(host,reward));
}

function createWeeklyRoleTag(reward) {
    if (!reward) return null;
    const tag = document.createElement("span");
    tag.className = "weekly-role-tag weekly-" + String(reward.tier || "top10");
    tag.style.setProperty("--weekly-accent", reward.accent || "#53E6FF");

    const icon = document.createElement("span");
    icon.className = "weekly-role-icon weekly-custom-badge-host";
    mountWeeklyBadge(icon,reward);

    const label = document.createElement("span");
    label.textContent = reward.badgeLabel || reward.title || "TOP";

    tag.appendChild(icon);
    tag.appendChild(label);
    return tag;
}

async function maybeTriggerWeeklyEntrance(data) {
    const key = userKey(data);
    if (!key || weeklyEntranceChecked.has(key)) return;
    weeklyEntranceChecked.add(key);

    try {
        const response = await fetch(
            "/api/weekly-rewards/entrance",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user: makeUserPayload(data) })
            }
        );
        if (!response.ok) {
            weeklyEntranceChecked.delete(key);
        }
    }
    catch (error) {
        weeklyEntranceChecked.delete(key);
    }
}

loadWeeklyRewards();
setInterval(loadWeeklyRewards, 10000);

async function refreshDirectIntegrationStatus() {
    try {
        const response = await fetch(
            "/api/integrations",
            { cache: "no-store" }
        );

        const data = await response.json();

        DIRECT_INTEGRATIONS.streamlabs =
            Boolean(
                data.streamlabs &&
                data.streamlabs.enabled &&
                data.streamlabs.tokenPresent
            );

        DIRECT_INTEGRATIONS.tikfinity =
            Boolean(
                data.tikfinity &&
                data.tikfinity.enabled
            );

        // Cuando TikFinity entrega eventos al servidor, este suma los likes
        // al ranking sin depender de ventanas de OBS. Omitir la copia SSN
        // impide que el mismo lote aporte puntos dos veces.
        DIRECT_INTEGRATIONS.tikfinityRankLikes = Boolean(
            data.tikfinity && data.tikfinity.enabled && data.tikfinity.connected
        );
    }
    catch (error) {
        // El fallback SSN sigue funcionando si el servidor no responde.
    }
}

function directIntegrationOwnsEconomy(
    data,
    economyEvent
) {
    if (!economyEvent) return false;

    const platform = normalizePlatform(
        data.type
    );

    const kind = economyEvent.kind;

    if (
        platform === "twitch" &&
        DIRECT_INTEGRATIONS.streamlabs &&
        ["follow", "subscription", "gift"].includes(kind)
    ) {
        return true;
    }

    if (
        platform === "tiktok" &&
        DIRECT_INTEGRATIONS.tikfinity &&
        ["follow", "subscription", "gift", "like"].includes(kind)
    ) {
        return true;
    }

    return false;
}

function directIntegrationOwnsAlert(data) {
    const platform = normalizePlatform(
        data.type
    );

    if (
        platform === "twitch" &&
        DIRECT_INTEGRATIONS.streamlabs
    ) {
        return true;
    }

    if (
        platform === "tiktok" &&
        DIRECT_INTEGRATIONS.tikfinity
    ) {
        return true;
    }

    return false;
}

refreshDirectIntegrationStatus();
setInterval(
    refreshDirectIntegrationStatus,
    5000
);

const IDLE_SECONDS = 10;
const MAX_MESSAGES = 12;

/*
  Puntuación por interacción.
  Puedes cambiarla sin tocar el resto del sistema.
*/
const SCORE = {
    message: 1,           // 1 mensaje = 1 punto
    like: 0.10,           // 10 corazones atribuibles = 1 punto
    follow: 10,           // follow = 10 puntos
    join: 0.5,            // entrar al LIVE = 0.5
    subscription: 50,     // suscripción = 50
    giftBase: 5,          // regalo sin valor conocido
    giftCoin: 1,          // 1 moneda TikTok = 1 punto
    donationUsd: 25       // $1 USD equivalente = 25 puntos
};

/*
  Tus propias cuentas y bots no compiten.
  Ajusta estos nombres si cambias de usuario.
*/
const EXCLUDED_USERS = [
    /* Las cuentas propietarias configuradas se filtran también en el servidor. */
    /* Bots tampoco compiten. */
    { platform: "*", username: "streamelements" },
    { platform: "*", username: "nightbot" },
    { platform: "*", username: "moobot" }
];

/*
  Usuarios que NO deben mostrarse visualmente en el chat.
  IMPORTANTE:
  Tus cuentas NO están aquí; puedes escribir y tus mensajes sí se verán.
*/
const BLOCKED_CHAT_USERS = [
    { platform: "*", username: "streamelements" },
    { platform: "*", username: "nightbot" },
    { platform: "*", username: "moobot" }
];


/*
  ECONOMÍA / GUMPITAS
  La puntuación semanal y las Gumpitas son sistemas distintos:
  - Ranking semanal = quién interactúa más esta semana.
  - Gumpitas = moneda persistente que se puede gastar.
*/
const COMMAND_PREFIX = "!";



/* ================= ELEMENTOS ================= */

const log = document.getElementById("log");
const bridge = document.getElementById("ssn_bridge");

const statusBox = document.getElementById("connection-status");
const statusTitle = document.getElementById("status-title");
const statusDetail = document.getElementById("status-detail");


/* ================= ESTADO ================= */

let idleTimer = null;
let removeTimer = null;

let websocket = null;
let websocketReconnectTimer = null;
let websocketAttempts = 0;

let p2pLoaded = false;
let websocketConnected = false;

let leaderboard = {
    period: "",
    top: [],
    ranking: []
};

const recentEvents = new Map();
let chatDesign={enabled:false,replaceDefaultCss:false,customHtml:"",customCss:"",customJs:""};
let chatDesignUpdatedAt="";
let layoutStudioUpdatedAt="";
let chatLayout={width:450,scale:100,position:"bottom-left",accent:"#76ff6a",backgroundOpacity:92,radius:14};

if (!DEBUG_VISIBLE) {
    statusBox.classList.add("hidden");
}


/* ================= UTILIDADES ================= */

function setStatus(state, title, detail) {
    statusBox.className = "status " + state;

    if (!DEBUG_VISIBLE) {
        statusBox.classList.add("hidden");
    }

    statusTitle.textContent = title || "";
    statusDetail.textContent = detail || "";
}


function refreshConnectionStatus() {
    const p2pText = p2pLoaded ? "P2P: cargado" : "P2P: iniciando";
    const wsText = websocketConnected ? "WS: conectado" : "WS: sin conexión";

    setStatus(
        websocketConnected ? "connected" : "connecting",
        websocketConnected
            ? "🟢 SOCIAL STREAM PREPARADO"
            : "🟡 SOCIAL STREAM PREPARANDO",
        p2pText + " · " + wsText + " · ranking local activo"
    );
}


function getSessionId() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("session");

    if (fromUrl && fromUrl.trim()) {
        return fromUrl.trim();
    }

    if (SOCIAL_STREAM_RUNTIME.sessionId) {
        return SOCIAL_STREAM_RUNTIME.sessionId;
    }

    if (
        SESSION_ID_MANUAL &&
        SESSION_ID_MANUAL !== "PON_AQUI_TU_SESSION_ID"
    ) {
        return SESSION_ID_MANUAL.trim();
    }

    return "";
}


function getPassword() {
    const params = new URLSearchParams(window.location.search);

    return (
        params.get("password") ||
        params.get("pass") ||
        params.get("pw") ||
        SOCIAL_STREAM_RUNTIME.password ||
        SESSION_PASSWORD_MANUAL ||
        "false"
    );
}


function normalizePlatform(type) {
    const t = String(type || "").toLowerCase();

    if (t.includes("twitch")) return "twitch";
    if (t.includes("tiktok")) return "tiktok";

    return t.replace(/[^a-z0-9_-]/g, "");
}


function normalizeUsername(username) {
    return String(username || "")
        .trim()
        .replace(/^@+/, "")
        .toLowerCase();
}


function userKey(data) {
    const platform = normalizePlatform(data.type);
    const username = normalizeUsername(data.chatname);

    if (!platform || !username) return "";

    return platform + ":" + username;
}


function isExcluded(data) {
    const platform = normalizePlatform(data.type);
    const username = normalizeUsername(data.chatname);

    if (!platform || !username) return true;

    if (data.bot === true || data.host === true || data.broadcaster === true) {
        return true;
    }

    return EXCLUDED_USERS.some(function (entry) {
        const p = String(entry.platform || "*").toLowerCase();
        const u = normalizeUsername(entry.username);

        return u === username && (p === "*" || p === platform);
    });
}


function isBlockedFromChat(data) {
    const platform = normalizePlatform(data.type);
    const username = normalizeUsername(data.chatname);

    if (!platform || !username) return false;

    return BLOCKED_CHAT_USERS.some(function (entry) {
        const p = String(entry.platform || "*").toLowerCase();
        const u = normalizeUsername(entry.username);

        return u === username && (p === "*" || p === platform);
    });
}


function platformIcon(type) {
    const platform = normalizePlatform(type);
    if (!platform) return "";

    return (
        "https://socialstream.ninja/sources/images/" +
        platform +
        ".png"
    );
}


function escapeHtml(value) {
    return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


/* ================= RANKING LOCAL ================= */

async function loadLeaderboard() {
    try {
        const response = await fetch("/api/ranking", {
            cache: "no-store"
        });

        if (!response.ok) return;

        leaderboard = await response.json();
    }
    catch (error) {
        console.warn("No se pudo leer el ranking:", error);
    }
}


async function saveInteraction(data, interaction) {
    if (!interaction || interaction.delta <= 0) return;
    if (isExcluded(data)) return;

    const key = userKey(data);
    if (!key) return;

    const body = {
        user: {
            key: key,
            platform: normalizePlatform(data.type),
            username: data.chatname || "Usuario",
            avatar: data.chatimg || ""
        },
        delta: interaction.delta,
        counters: interaction.counters
    };

    try {
        const response = await fetch("/api/interaction", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body)
        });

        if (!response.ok) return;

        leaderboard = await response.json();
    }
    catch (error) {
        console.warn("No se pudo guardar interacción:", error);
    }
}


function getAutomaticRole(data) {
    const key = userKey(data);
    if (!key || !Array.isArray(leaderboard.top)) return null;

    const found = leaderboard.top.find(function (entry) {
        return entry.key === key;
    });

    if (!found) return null;

    if (found.rank === 1) {
        return {
            className: "top-1",
            label: "VIEWER DE LA SEMANA",
            icon: "👑"
        };
    }

    if (found.rank === 2) {
        return {
            className: "top-2",
            label: "GUMPITA DESTACADA",
            icon: "🥈"
        };
    }

    if (found.rank === 3) {
        return {
            className: "top-3",
            label: "GUMPITA DESTACADA",
            icon: "🥉"
        };
    }

    return null;
}


/* ================= DETECCIÓN DE INTERACCIONES ================= */

function numberFrom(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
        return value;
    }

    const match = String(value || "")
        .replace(/,/g, "")
        .match(/-?\d+(?:\.\d+)?/);

    return match ? Number(match[0]) : 0;
}


function extractLikeCount(data) {
    const event = String(data.event || "").toLowerCase();

    /*
      likes_update es un TOTAL de plataforma, no de una persona.
      No lo usamos para un ranking individual.
    */
    if (event === "likes_update") {
        return 0;
    }

    if (!event.includes("like")) {
        return 0;
    }

    if (!data.chatname) {
        return 0;
    }

    if (data.meta && typeof data.meta === "object") {
        const candidates = [
            data.meta.count,
            data.meta.likes,
            data.meta.likeCount,
            data.meta.like_count,
            data.meta.repeatCount,
            data.meta.repeat_count
        ];

        for (const candidate of candidates) {
            const n = numberFrom(candidate);
            if (n > 0) return Math.floor(n);
        }
    }

    const metaNumber = numberFrom(data.meta);
    if (metaNumber > 0) return Math.floor(metaNumber);

    const messageNumber = numberFrom(data.chatmessage);
    if (messageNumber > 0) return Math.floor(messageNumber);

    return 1;
}


function extractGiftCoins(data) {
    if (data.meta && typeof data.meta === "object") {
        const candidates = [
            data.meta.coins,
            data.meta.coin,
            data.meta.coinValue,
            data.meta.diamondCount,
            data.meta.value
        ];

        for (const candidate of candidates) {
            const n = numberFrom(candidate);
            if (n > 0) return Math.floor(n);
        }
    }

    const donation = String(data.hasDonation || "");
    const coinMatch = donation
        .replace(/,/g, "")
        .match(/(\d+(?:\.\d+)?)\s*(?:coin|coins|moneda|monedas)/i);

    if (coinMatch) {
        return Math.floor(Number(coinMatch[1]));
    }

    return 0;
}


function detectInteraction(data) {
    if (!data || typeof data !== "object") return null;
    if (!data.chatname) return null;
    if (isExcluded(data)) return null;

    const event = String(data.event || "").toLowerCase();
    const hasDonation = Boolean(data.hasDonation);
    const donoValue = Number(data.donoValue);

    /*
      1) Regalo / donación / bits.
      Tiene prioridad sobre el mensaje de texto del mismo evento.
    */
    if (
        hasDonation ||
        event.includes("gift") ||
        event === "cheer" ||
        event === "donation" ||
        event.includes("superchat") ||
        event.includes("supersticker")
    ) {
        const coins = extractGiftCoins(data);

        if (Number.isFinite(donoValue) && donoValue > 0) {
            return {
                delta: donoValue * SCORE.donationUsd,
                counters: {
                    gifts: 1,
                    donationUsd: donoValue
                }
            };
        }

        if (coins > 0) {
            return {
                delta: coins * SCORE.giftCoin,
                counters: {
                    gifts: 1,
                    giftCoins: coins
                }
            };
        }

        return {
            delta: SCORE.giftBase,
            counters: {
                gifts: 1
            }
        };
    }

    /*
      2) Suscripciones.
    */
    if (
        event.includes("subscriber") ||
        event === "subscription" ||
        event === "resub" ||
        Boolean(data.membership && !data.chatmessage)
    ) {
        return {
            delta: SCORE.subscription,
            counters: {
                subscriptions: 1
            }
        };
    }

    /*
      3) Follow.
    */
    if (
        event === "new_follower" ||
        event === "follow"
    ) {
        return {
            delta: SCORE.follow,
            counters: {
                follows: 1
            }
        };
    }

    /*
      4) Likes/corazones atribuibles a una persona.
    */
    const likes = extractLikeCount(data);

    if (likes > 0) {
        return {
            delta: likes * SCORE.like,
            counters: {
                likes: likes
            }
        };
    }

    /*
      5) Entrada al LIVE.
    */
    if (
        event === "join" ||
        event === "user_join" ||
        event === "member_join"
    ) {
        return {
            delta: SCORE.join,
            counters: {
                joins: 1
            }
        };
    }

    /*
      6) Mensaje normal.
    */
    if (
        data.chatmessage &&
        !event
    ) {
        return {
            delta: SCORE.message,
            counters: {
                messages: 1
            }
        };
    }

    return null;
}


/* ================= DEDUPE P2P + WEBSOCKET ================= */

function eventFingerprint(data) {
    return JSON.stringify([
        data.id || data.mid || "",
        normalizePlatform(data.type),
        data.chatname || "",
        data.event || "",
        data.chatmessage || "",
        data.hasDonation || "",
        JSON.stringify(data.meta || "")
    ]);
}


function isDuplicateEvent(data) {
    const key = eventFingerprint(data);
    const now = Date.now();

    recentEvents.forEach(function (time, savedKey) {
        if (now - time > 5000) {
            recentEvents.delete(savedKey);
        }
    });

    if (recentEvents.has(key)) {
        return true;
    }

    recentEvents.set(key, now);
    return false;
}


/* ================= ROLES NATIVOS ================= */

function getNativeRoleClasses(data) {
    const roles = [];

    const badgeBlob = JSON.stringify(data.chatbadges || "").toLowerCase();
    const membership = String(data.membership || "").toLowerCase();

    if (
        data.subscriber === true ||
        badgeBlob.includes("subscriber") ||
        badgeBlob.includes("subscription") ||
        membership.includes("member") ||
        membership.includes("sub")
    ) {
        roles.push("subscriber");
    }

    if (
        data.vip === true ||
        badgeBlob.includes("vip")
    ) {
        roles.push("vip");
    }

    if (
        data.mod === true ||
        data.moderator === true ||
        badgeBlob.includes("moderator")
    ) {
        roles.push("mod");
    }

    if (
        data.host === true ||
        data.broadcaster === true ||
        badgeBlob.includes("broadcaster") ||
        badgeBlob.includes("owner")
    ) {
        roles.push("broadcaster");
    }

    return roles;
}


function getDisplayRole(data, nativeRoles) {
    if (nativeRoles.includes("broadcaster")) {
        return {
            className: "broadcaster",
            label: "STREAMER",
            icon: "🎃"
        };
    }

    const automatic = getAutomaticRole(data);
    if (automatic) return automatic;

    if (nativeRoles.includes("mod")) {
        return {
            className: "mod",
            label: "MOD",
            icon: "🩸"
        };
    }

    if (nativeRoles.includes("vip")) {
        return {
            className: "vip",
            label: "VIP",
            icon: "✦"
        };
    }

    if (nativeRoles.includes("subscriber")) {
        return {
            className: "subscriber",
            label: "SUB",
            icon: "★"
        };
    }

    return null;
}


function createRoleTag(role) {
    if (!role) return null;

    const tag = document.createElement("span");
    tag.className = "role-tag";

    const icon = document.createElement("span");
    icon.className = "role-tag-icon";
    icon.textContent = role.icon || "✦";

    const label = document.createElement("span");
    label.textContent = role.label || "";

    tag.appendChild(icon);
    tag.appendChild(label);

    return tag;
}


/* ================= BADGES ================= */

function renderSingleBadge(badge) {
    if (!badge) return "";

    if (typeof badge === "string") {
        if (
            badge.startsWith("http://") ||
            badge.startsWith("https://") ||
            badge.startsWith("data:")
        ) {
            return '<img class="badge" src="' + escapeHtml(badge) + '" alt="">';
        }

        return '<span class="badge-text">' + escapeHtml(badge) + '</span>';
    }

    const src = badge.src || badge.url || badge.image || badge.img;

    if (src) {
        return '<img class="badge" src="' + escapeHtml(src) + '" alt="">';
    }

    const text = badge.rawText || badge.text || badge.name;

    if (text) {
        return '<span class="badge-text">' + escapeHtml(text) + '</span>';
    }

    return "";
}


function renderBadges(data) {
    const badges = data.chatbadges;

    if (!badges) return "";

    if (Array.isArray(badges)) {
        return badges.map(renderSingleBadge).join("");
    }

    if (typeof badges === "string") {
        return renderSingleBadge(badges);
    }

    return "";
}



/* ================= GUMPITAS / COMANDOS ================= */

function getCommandFromMessage(data) {
    if (!data || !data.chatmessage) return null;

    const text = String(data.chatmessage).trim();

    if (!text.startsWith(COMMAND_PREFIX)) {
        return null;
    }

    return text;
}


function economyKindFromData(data, commandText) {
    /*
      Los comandos NO generan Gumpitas por mensaje.
      Así evitamos farmear !gumpitas / !tienda.
    */
    if (commandText) {
        return null;
    }

    if (!data || typeof data !== "object") {
        return null;
    }

    if (isExcluded(data)) {
        return null;
    }

    const event = String(data.event || "").toLowerCase();
    const hasDonation = Boolean(data.hasDonation);
    const donoValue = Number(data.donoValue);

    if (
        hasDonation ||
        event.includes("gift") ||
        event === "cheer" ||
        event === "donation" ||
        event.includes("superchat") ||
        event.includes("supersticker")
    ) {
        return {
            kind: "gift",
            quantity: 1,
            giftCoins: extractGiftCoins(data),
            donationUsd:
                Number.isFinite(donoValue) && donoValue > 0
                    ? donoValue
                    : 0
        };
    }

    if (
        event.includes("subscriber") ||
        event === "subscription" ||
        event === "resub" ||
        Boolean(data.membership && !data.chatmessage)
    ) {
        return {
            kind: "subscription",
            quantity: 1
        };
    }

    if (
        event === "new_follower" ||
        event === "follow"
    ) {
        return {
            kind: "follow",
            quantity: 1
        };
    }

    const likes = extractLikeCount(data);

    if (likes > 0) {
        return {
            kind: "like",
            quantity: likes
        };
    }

    if (
        event === "join" ||
        event === "user_join" ||
        event === "member_join"
    ) {
        return {
            kind: "join",
            quantity: 1
        };
    }

    if (data.chatmessage && !event) {
        return {
            kind: "message",
            quantity: 1
        };
    }

    return null;
}


function makeUserPayload(data) {
    return {
        key: userKey(data),
        platform: normalizePlatform(data.type),
        username: data.chatname || "Usuario",
        avatar: data.chatimg || ""
    };
}


async function saveEconomyInteraction(data, economyEvent) {
    if (!economyEvent) return;
    if (isExcluded(data)) return;

    const user = makeUserPayload(data);

    if (!user.key) {
        return;
    }

    try {
        await fetch("/api/economy/earn", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                user: user,
                kind: economyEvent.kind,
                quantity: economyEvent.quantity || 1,
                giftCoins: economyEvent.giftCoins || 0,
                donationUsd: economyEvent.donationUsd || 0
            })
        });
    }
    catch (error) {
        console.warn(
            "No se pudieron guardar Gumpitas:",
            error
        );
    }
}


async function sendCommandToServer(data, commandText) {
    if (!commandText) return;

    /*
      Los bots bloqueados no pueden ejecutar comandos.
      Tus propias cuentas sí pueden usarlos para hacer pruebas.
    */
    if (isBlockedFromChat(data)) {
        return;
    }

    const user = makeUserPayload(data);

    if (!user.key) {
        return;
    }

    try {
        await fetch("/api/command", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                user: user,
                command: commandText
            })
        });
    }
    catch (error) {
        console.warn(
            "No se pudo ejecutar el comando:",
            error
        );
    }
}


/* ================= DISEÑO PERSONALIZABLE DEL CHAT ================= */

function chatTokenEscape(value){return escapeHtml(value==null?"":value);}

function applyChatDesign(design){
    chatDesign=design&&typeof design==='object'?design:chatDesign;

    const base=document.getElementById('base-chat-style');
    if(base)base.disabled=Boolean(chatDesign.enabled&&chatDesign.replaceDefaultCss);

    let style=document.getElementById('chat-custom-style');
    if(!style){style=document.createElement('style');style.id='chat-custom-style';document.head.appendChild(style);}
    style.textContent=chatDesign.enabled?String(chatDesign.customCss||''):'';
}

async function loadChatDesign(){
    try{
        const response=await fetch('/api/chat-design',{cache:'no-store'});
        if(!response.ok)return;
        const payload=await response.json();
        const design=payload.design||{};
        if(String(design.updatedAt||'')!==chatDesignUpdatedAt){
            chatDesignUpdatedAt=String(design.updatedAt||'');
            applyChatDesign(design);
        }
    }catch(error){console.warn('No se pudo cargar diseño del chat:',error);}
}

function applyChatLayout(layout){
    if(!layout||typeof layout!=='object')return;
    chatLayout={...chatLayout,...layout};

    const width=Math.max(220,Math.min(1600,Number(chatLayout.width||450)));
    const scale=Math.max(.5,Math.min(1.8,Number(chatLayout.scale||100)/100));
    const pos=String(chatLayout.position||'bottom-left');

    log.style.width=width+'px';
    log.style.left='auto';log.style.right='auto';log.style.top='auto';log.style.bottom='auto';
    log.style.transform=`scale(${scale})`;

    if(pos.includes('right')){
        log.style.right='0';
        log.style.transformOrigin=pos.startsWith('top')?'top right':'bottom right';
    }else{
        log.style.left='0';
        log.style.transformOrigin=pos.startsWith('top')?'top left':'bottom left';
    }
    if(pos.startsWith('top'))log.style.top='0';else log.style.bottom='0';

    const opacity=Math.max(0,Math.min(100,Number(chatLayout.backgroundOpacity||92)))/100;
    const radius=Math.max(0,Math.min(48,Number(chatLayout.radius||14)));
    const accent=/^#[0-9a-f]{6}$/i.test(String(chatLayout.accent||''))?chatLayout.accent:'#76ff6a';

    let style=document.getElementById('layout-studio-chat-style');
    if(!style){style=document.createElement('style');style.id='layout-studio-chat-style';document.head.appendChild(style);}
    style.textContent=`
      #log .message{background:rgba(18,13,22,${opacity})!important;border-radius:${radius}px;}
      #log>div::after{box-shadow:0 0 10px ${accent};}
    `;
}

async function loadLayoutStudio(){
    try{
        const response=await fetch('/api/layout-studio',{cache:'no-store'});
        if(!response.ok)return;
        const payload=await response.json();
        const layout=payload.layout||{};
        const updated=String(layout.updatedAt||'');
        if(updated!==layoutStudioUpdatedAt){
            layoutStudioUpdatedAt=updated;
            applyChatLayout(layout.chat||{});
        }
    }catch(error){console.warn('[Brynn Chat] layout studio:',error);}
}

loadLayoutStudio();
setInterval(loadLayoutStudio,4000);

function customChatMessage(wrapper,data,platform,displayRole,visibleText){
    if(!chatDesign.enabled||!String(chatDesign.customHtml||'').trim())return false;

    const role=displayRole||{};
    const weekly=weeklyRewardFor(data)||{};
    const iconUrl=platformIcon(platform);
    const badgesHtml=renderBadges(data);
    const message=messageHtml({chatmessage:visibleText,textonly:data.textonly});
    const contentImage=data.contentimg?`<img class="content-image" src="${chatTokenEscape(data.contentimg)}" alt="">`:'';
    const roleTag=displayRole?`<span class="role-tag"><span class="role-tag-icon">${chatTokenEscape(role.icon||'✦')}</span><span>${chatTokenEscape(role.label||'')}</span></span>`:'';
    const weeklyTag=weekly&&weekly.tier?`<span class="weekly-role-tag weekly-${chatTokenEscape(weekly.tier)}" style="--weekly-accent:${chatTokenEscape(weekly.accent||'#53E6FF')}"><span class="weekly-role-icon weekly-custom-badge-host"></span><span>${chatTokenEscape(weekly.badgeLabel||weekly.title||'TOP')}</span></span>`:'';

    const tokens={
        '{user}':chatTokenEscape(data.chatname||'Usuario'),
        '{platform}':chatTokenEscape(platform.toUpperCase()),
        '{avatar}':chatTokenEscape(data.chatimg||''),
        '{platformIcon}':chatTokenEscape(iconUrl||''),
        '{badges}':badgesHtml,
        '{message}':message,
        '{contentImage}':contentImage,
        '{role}':chatTokenEscape(role.label||''),
        '{roleIcon}':chatTokenEscape(role.icon||''),
        '{roleTag}':roleTag,
        '{weeklyTitle}':chatTokenEscape(weekly.title||''),
        '{weeklyBadge}':chatTokenEscape(weekly.badgeLabel||''),
        '{weeklyRank}':chatTokenEscape(weekly.rank||''),
        '{weeklyTier}':chatTokenEscape(weekly.tier||''),
        '{weeklyTag}':weeklyTag
    };

    let html=String(chatDesign.customHtml||'');
    for(const [token,value] of Object.entries(tokens))html=html.split(token).join(value);
    wrapper.innerHTML=html;
    hydrateWeeklyBadgeHosts(wrapper,weekly);

    try{
        window.CHAT_DATA={
            user:data.chatname||'Usuario',platform,message:visibleText,
            avatar:data.chatimg||'',role:role.label||'',roleIcon:role.icon||'',
            weeklyTitle:weekly.title||'',weeklyBadge:weekly.badgeLabel||'',
            weeklyRank:weekly.rank||null,weeklyTier:weekly.tier||'',weekly:weekly,
            badges:data.chatbadges||[],raw:data
        };
        window.CHAT_ELEMENT=wrapper;
        if(String(chatDesign.customJs||'').trim()){
            new Function('CHAT_DATA','CHAT_ELEMENT',String(chatDesign.customJs))(window.CHAT_DATA,wrapper);
        }
    }catch(error){console.warn('[Brynn Chat custom JS]',error);}

    return true;
}

loadChatDesign();
setInterval(loadChatDesign,4000);

/* ================= CHAT VISUAL ================= */

function shouldDisplayInChat(data) {
    if (!data || typeof data !== "object") return false;

    /*
      Separado del ranking:
      - EXCLUDED_USERS = no suman puntos.
      - BLOCKED_CHAT_USERS = no se muestran.
      Así tu propia cuenta puede escribir en el chat sin competir en el Top 3.
    */
    if (isBlockedFromChat(data)) return false;

    /*
      No llenamos el chat con likes/joins/contadores.
      Sí mostramos mensajes y eventos de apoyo con texto/valor.
    */
    if (data.chatmessage) return true;
    if (data.hasDonation) return true;
    if (data.membership) return true;

    return false;
}


function messageHtml(data) {
    const value = data.chatmessage || "";

    // Chat messages may originate from third-party integrations. Always escape them;
    // formatting must be implemented through trusted, structured UI data instead.
    return escapeHtml(value);
}


function addMessage(data, transport) {
    if (!shouldDisplayInChat(data)) return;

    const platform = normalizePlatform(data.type) || "ssn";
    const nativeRoles = getNativeRoleClasses(data);
    const displayRole = getDisplayRole(data, nativeRoles);
    const weeklyReward = weeklyRewardFor(data);

    const wrapper = document.createElement("div");

    wrapper.dataset.from = data.chatname || "";
    wrapper.dataset.platform = platform;
    wrapper.dataset.transport = transport;

    nativeRoles.forEach(function (role) {
        wrapper.classList.add(role);
    });

    if (displayRole) {
        wrapper.classList.add(displayRole.className);
    } else {
        wrapper.classList.add("no-role-tag");
    }
    if (weeklyReward) {
        wrapper.classList.add("weekly-reward-user", "weekly-" + String(weeklyReward.tier || "top10"));
        wrapper.style.setProperty("--weekly-accent", weeklyReward.accent || "#53E6FF");
    }

    const visibleText =
        data.chatmessage ||
        data.subtitle ||
        data.membership ||
        data.hasDonation ||
        "";

    const usedCustom = customChatMessage(
        wrapper,
        data,
        platform,
        displayRole,
        visibleText
    );

    if (!usedCustom) {
        const weeklyTag = createWeeklyRoleTag(weeklyReward);
        const tag = createRoleTag(displayRole);

        if (weeklyTag) {
            wrapper.appendChild(weeklyTag);
        }
        if (tag) {
            wrapper.appendChild(tag);
        }

        const meta = document.createElement("span");
        meta.className = "meta";

        const iconUrl = platformIcon(platform);

        if (iconUrl) {
            const icon = document.createElement("img");
            icon.className = "platform-icon";
            icon.src = iconUrl;
            icon.alt = platform;
            icon.onerror = function () { icon.remove(); };
            meta.appendChild(icon);
        }

        const badges = document.createElement("span");
        badges.className = "badges";
        badges.innerHTML = renderBadges(data);
        meta.appendChild(badges);

        const name = document.createElement("span");
        name.className = "name";
        name.textContent = data.chatname || "Usuario";
        meta.appendChild(name);

        const message = document.createElement("span");
        message.className = "message";
        message.innerHTML = messageHtml({
            chatmessage: visibleText,
            textonly: data.textonly
        });

        if (data.contentimg) {
            const image = document.createElement("img");
            image.className = "content-image";
            image.src = data.contentimg;
            image.alt = "";
            image.onerror = function () { image.remove(); };

            message.appendChild(document.createElement("br"));
            message.appendChild(image);
        }

        wrapper.appendChild(meta);
        wrapper.appendChild(message);
    }

    log.appendChild(wrapper);

    while (log.children.length > MAX_MESSAGES) {
        log.removeChild(log.firstElementChild);
    }

    resetIdleTimer();
}


/* ================= TEMPORIZADOR ================= */

function resetIdleTimer() {
    clearTimeout(idleTimer);
    clearTimeout(removeTimer);

    log.classList.remove("idle-fade");

    idleTimer = setTimeout(function () {
        if (!log.children.length) return;

        log.classList.add("idle-fade");

        removeTimer = setTimeout(function () {
            log.innerHTML = "";
            log.classList.remove("idle-fade");
        }, 800);

    }, IDLE_SECONDS * 1000);
}



/* ================= MONITOR DE EVENTOS CRUDOS ================= */

async function logRawIncomingEvent(data, source = "ssn") {
    if (!data || typeof data !== "object") return;

    const interesting =
        Boolean(data.event) ||
        Boolean(data.hasDonation) ||
        Boolean(data.membership);

    if (!interesting) return;

    try {
        await fetch("/api/debug-event", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source, payload: data })
        });
    } catch (error) {
        console.warn("No se pudo registrar evento crudo:", error);
    }
}


/* ================= ALERTAS FOLLOW / SUB / GIFT ================= */

function normalizeAlertEventName(value) {
    const raw = String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");

    const aliases = {
        follow: "new_follower",
        followed: "new_follower",
        channel_followed: "new_follower",
        follower_added: "new_follower",

        subscribe: "subscription",
        subscriber: "subscription",
        new_subscriber: "subscription",
        new_subscription: "subscription",
        channel_subscription: "subscription",
        channel_subscription_new: "subscription",
        channel_subscription_start: "subscription",
        sponsorship: "subscription",
        resub: "subscription",
        subscription_renewal: "subscription",
        channel_subscription_renewal: "subscription",

        gifted: "gift",
        giftpurchase: "gift",
        subscription_gift: "gift",
        subgift: "gift",
        donation: "gift",
        cheer: "gift",
        superchat: "gift",
        supersticker: "gift"
    };

    return aliases[raw] || raw;
}

function detectStreamAlert(data) {
    if (!data || typeof data !== "object") return null;

    const platform = normalizePlatform(data.type);
    if (!["twitch", "tiktok"].includes(platform)) return null;

    const event = normalizeAlertEventName(data.event);

    if (
        data.hasDonation ||
        event === "gift" ||
        String(data.event || "").toLowerCase().includes("gift")
    ) {
        let amount = "";
        const coins = extractGiftCoins(data);
        const dono = Number(data.donoValue);

        if (Number.isFinite(dono) && dono > 0) {
            amount = `$${dono.toFixed(2)}`;
        } else if (coins > 0) {
            amount = `${coins} monedas`;
        } else if (data.hasDonation) {
            amount = String(data.hasDonation);
        } else if (data.subtitle) {
            amount = String(data.subtitle);
        }

        return { type: "gift", amount };
    }

    if (
        event === "subscription" ||
        Boolean(data.membership && !data.chatmessage)
    ) {
        return {
            type: "subscription",
            amount: String(data.membership || data.subtitle || "")
        };
    }

    if (event === "new_follower") {
        return { type: "follow", amount: "" };
    }

    return null;
}


async function sendStreamAlert(data, alert) {
    if (!alert) return;

    try {
        await fetch("/api/alert", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                platform: normalizePlatform(data.type),
                type: alert.type,
                username: data.chatname || "Usuario",
                avatar: data.chatimg || "",
                amount: alert.amount || ""
            })
        });
    }
    catch (error) {
        console.warn(
            "No se pudo enviar alerta del stream:",
            error
        );
    }
}


/* ================= ENTRADA CENTRAL ================= */

async function handleIncoming(data, transport) {
    if (!data || typeof data !== "object") return;
    if (isDuplicateEvent(data)) return;

    // V0.44: espejo persistente para la ventana flotante. El servidor deduplica
    // si la ventana flotante y el overlay OBS reciben el mismo paquete.
    if (transport !== 'Kick API') fetch('/api/chat/ingest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:transport||'ssn',data})}).catch(()=>{});

    logRawIncomingEvent(
        data,
        transport === "TikFinity" ? "tikfinity" : "ssn"
    );

    const commandText = getCommandFromMessage(data);
    const streamAlert = detectStreamAlert(data);

    /*
      Alertas de follow / suscripción / regalo.
      Se procesan una sola vez gracias al dedupe P2P + WebSocket.
    */
    if (
        streamAlert &&
        !directIntegrationOwnsAlert(data)
    ) {
        await sendStreamAlert(
            data,
            streamAlert
        );
    }

    /*
      1) Ranking semanal.
      Los comandos siguen contando como interacción del ranking.
    */
    const interaction = detectInteraction(data);
    const directTikTokLikes = (
        normalizePlatform(data.type) === "tiktok" &&
        DIRECT_INTEGRATIONS.tikfinityRankLikes &&
        extractLikeCount(data) > 0
    );

    if (interaction && !directTikTokLikes) {
        await saveInteraction(data, interaction);
    }

    /*
      2) Gumpitas persistentes.
      Un comando no otorga la recompensa de "mensaje".
    */
    const economyEvent =
        economyKindFromData(
            data,
            commandText
        );

    if (
        economyEvent &&
        !directIntegrationOwnsEconomy(
            data,
            economyEvent
        )
    ) {
        await saveEconomyInteraction(
            data,
            economyEvent
        );
    }

    /*
      3) Comandos.
      La respuesta sale en events_overlay.html.
    */
    if (commandText) {
        await sendCommandToServer(
            data,
            commandText
        );
    }

    /*
      4) Entrada especial de ganadores semanales.
      El servidor aplica el cooldown; no bloqueamos el chat mientras responde.
    */
    maybeTriggerWeeklyEntrance(data);

    /*
      5) Chat visual normal.
    */
    addMessage(data, transport);

    if (DEBUG_VISIBLE) {
        const automatic = getAutomaticRole(data);

        setStatus(
            "message",
            "🟢 EVENTO RECIBIDO",
            normalizePlatform(data.type) +
            " • " +
            (data.chatname || "sin usuario") +
            (automatic ? " • " + automatic.label : "")
        );
    }
}


/* ================= P2P ================= */

function connectP2P() {
    const session = getSessionId();

    if (!session) {
        setStatus(
            "error",
            "🔴 FALTA EL SESSION ID",
            "Agrégalo en SESSION_ID_MANUAL"
        );
        return;
    }

    const password = getPassword();

    bridge.src =
        "https://vdo.socialstream.ninja/" +
        "?ln" +
        "&salt=vdo.ninja" +
        "&password=" + encodeURIComponent(password) +
        "&push" +
        "&label=dock" +
        "&vd=0" +
        "&ad=0" +
        "&novideo" +
        "&noaudio" +
        "&autostart" +
        "&cleanoutput" +
        "&room=" + encodeURIComponent(session);

    bridge.addEventListener(
        "load",
        function () {
            p2pLoaded = true;
            refreshConnectionStatus();
        },
        { once: true }
    );
}


window.addEventListener("message", function (event) {
    const packet = event.data;

    if (!packet || typeof packet !== "object") return;

    if (
        packet.dataReceived &&
        packet.dataReceived.overlayNinja
    ) {
        handleIncoming(
            packet.dataReceived.overlayNinja,
            "P2P"
        );
        return;
    }

    if (packet.overlayNinja) {
        handleIncoming(
            packet.overlayNinja,
            "P2P"
        );
    }
});


/* ================= WEBSOCKET CHANNEL 4 ================= */

function connectWebSocket() {
    const session = getSessionId();
    if (!session) return;

    clearTimeout(websocketReconnectTimer);

    const wsUrl =
        "wss://io.socialstream.ninja/join/" +
        encodeURIComponent(session) +
        "/4";

    try {
        websocket = new WebSocket(wsUrl);
    }
    catch (error) {
        websocketConnected = false;
        scheduleWebSocketReconnect();
        return;
    }

    websocket.onopen = function () {
        websocketAttempts = 0;
        websocketConnected = true;
        refreshConnectionStatus();
    };

    websocket.onmessage = function (event) {
        if (!event.data) return;

        try {
            const data = JSON.parse(event.data);

            if (
                data.dataReceived &&
                data.dataReceived.overlayNinja
            ) {
                handleIncoming(
                    data.dataReceived.overlayNinja,
                    "WebSocket"
                );
            }
            else if (data.overlayNinja) {
                handleIncoming(
                    data.overlayNinja,
                    "WebSocket"
                );
            }
            else {
                handleIncoming(
                    data,
                    "WebSocket"
                );
            }
        }
        catch (error) {
            console.warn("Mensaje WS no interpretable:", event.data);
        }
    };

    websocket.onerror = function () {
        websocketConnected = false;
        refreshConnectionStatus();
    };

    websocket.onclose = function () {
        websocketConnected = false;
        refreshConnectionStatus();
        scheduleWebSocketReconnect();
    };
}


function scheduleWebSocketReconnect() {
    websocketAttempts++;

    const wait = Math.min(
        1000 * websocketAttempts,
        10000
    );

    websocketReconnectTimer = setTimeout(
        connectWebSocket,
        wait
    );
}


/* ================= TIKFINITY DIRECT FALLBACK ================= */

let tikfinitySocket = null;
let tikfinityReconnectTimer = null;
let tikfinityReconnectAttempts = 0;

function pickFirst(...values) {
    for (const value of values) {
        if (value !== undefined && value !== null && String(value).trim() !== "") {
            return value;
        }
    }
    return "";
}

function tikfinityUserInfo(data) {
    const user = data && typeof data.user === "object" ? data.user : {};

    const username = pickFirst(
        data?.uniqueId,
        data?.username,
        data?.nickname,
        data?.displayName,
        user?.uniqueId,
        user?.username,
        user?.nickname,
        user?.displayName,
        user?.name
    );

    const avatar = pickFirst(
        data?.profilePictureUrl,
        data?.avatarUrl,
        data?.thumbnailUrl,
        user?.profilePictureUrl,
        user?.avatarUrl,
        user?.thumbnailUrl,
        user?.profilePicture?.url
    );

    return {
        username: String(username || "Usuario TikTok"),
        avatar: String(avatar || "")
    };
}

function tikfinityGiftCoins(data) {
    const repeatCount = Math.max(
        1,
        Number(pickFirst(data?.repeatCount, data?.repeat_count, data?.gift?.repeatCount, 1)) || 1
    );

    const perGift = Number(pickFirst(
        data?.diamondCount,
        data?.diamond_count,
        data?.gift?.diamondCount,
        data?.giftDetails?.diamondCount,
        data?.extendedGiftInfo?.diamondCount,
        0
    )) || 0;

    const explicitCoins = Number(pickFirst(
        data?.coins,
        data?.coinValue,
        data?.coin_value,
        0
    )) || 0;

    if (explicitCoins > 0) return Math.round(explicitCoins);
    if (perGift > 0) return Math.round(perGift * repeatCount);
    return 0;
}

function normalizeTikfinityEvent(packet) {
    if (!packet || typeof packet !== "object") return null;

    const eventName = String(
        packet.event || packet.type || packet.eventType || ""
    ).toLowerCase();

    const data = packet.data && typeof packet.data === "object"
        ? packet.data
        : packet;

    const info = tikfinityUserInfo(data);

    if (eventName === "follow" || eventName.includes("follow")) {
        return {
            type: "tiktok",
            event: "followed",
            chatname: info.username,
            chatimg: info.avatar,
            _source: "tikfinity",
            _tikfinityRawEvent: eventName
        };
    }

    if (eventName === "subscribe" || eventName.includes("subscribe")) {
        return {
            type: "tiktok",
            event: "subscribe",
            membership: "SUBSCRIBER",
            subtitle: String(pickFirst(data?.subMonth, data?.months, data?.month, "")),
            chatname: info.username,
            chatimg: info.avatar,
            _source: "tikfinity",
            _tikfinityRawEvent: eventName
        };
    }

    if (eventName === "gift" || eventName.includes("gift")) {
        const coins = tikfinityGiftCoins(data);

        return {
            type: "tiktok",
            event: "gift",
            chatname: info.username,
            chatimg: info.avatar,
            hasDonation: coins > 0 ? `${coins} coins` : "TikTok Gift",
            meta: {
                coins,
                repeatCount: Number(data?.repeatCount || 1) || 1,
                giftName: String(pickFirst(
                    data?.giftName,
                    data?.gift?.name,
                    data?.giftDetails?.giftName,
                    ""
                ))
            },
            _source: "tikfinity",
            _tikfinityRawEvent: eventName
        };
    }

    return null;
}

function scheduleTikfinityReconnect() {
    if (!TIKFINITY_FALLBACK_ENABLED) return;

    clearTimeout(tikfinityReconnectTimer);
    tikfinityReconnectAttempts++;

    const delay = Math.min(1500 * tikfinityReconnectAttempts, 15000);
    tikfinityReconnectTimer = setTimeout(connectTikfinityFallback, delay);
}

function connectTikfinityFallback() {
    if (!TIKFINITY_FALLBACK_ENABLED) return;

    clearTimeout(tikfinityReconnectTimer);

    try {
        tikfinitySocket = new WebSocket(TIKFINITY_WS_URL);
    } catch (error) {
        console.warn("TikFinity WS no pudo abrirse:", error);
        scheduleTikfinityReconnect();
        return;
    }

    tikfinitySocket.onopen = function () {
        tikfinityReconnectAttempts = 0;
        console.log("[Brynn] TikFinity Event API conectada");
    };

    tikfinitySocket.onmessage = function (event) {
        try {
            const packet = JSON.parse(event.data);
            const normalized = normalizeTikfinityEvent(packet);

            if (normalized) {
                handleIncoming(normalized, "TikFinity");
            }
        } catch (error) {
            console.warn("TikFinity envió un paquete no interpretable:", error);
        }
    };

    tikfinitySocket.onclose = function () {
        scheduleTikfinityReconnect();
    };

    tikfinitySocket.onerror = function () {};
}


/* ============ KICK OFICIAL · MISMA ENTRADA CENTRAL ============ */
let kickChatLast=0;
let kickChatInitialized=false;
let kickChatPolling=false;
async function pollKickChat(){
    if(kickChatPolling)return;
    kickChatPolling=true;
    try{
        const r=await fetch(`/api/chat/messages?after=${kickChatLast}`,{cache:'no-store'});
        if(!r.ok)return;
        const d=await r.json();
        // Evitar reproducir mensajes históricos al arrancar OBS por primera vez.
        if(!kickChatInitialized){kickChatLast=Number(d.latestId)||0;kickChatInitialized=true;return;}
        for(const row of d.messages||[]){
            kickChatLast=Math.max(kickChatLast,Number(row.id)||0);
            if(row.source!=='kick'||row.platform!=='kick')continue;
            const raw=row.raw||{};
            const msg={...raw,type:'kick',chatname:row.username,chatmessage:row.message,
                       chatimg:row.avatar,textonly:true,mid:raw.mid||String(row.id)};
            await handleIncoming(msg,'Kick API');
        }
        kickChatLast=Math.max(kickChatLast,Number(d.latestId)||0);
    }catch(e){console.warn('Kick: no se pudo consultar el chat',e)}
    finally{kickChatPolling=false;}
}

/* ================= ARRANQUE ================= */

async function start() {
    await loadLeaderboard();
    await loadSocialStreamRuntime();

    connectP2P();
    connectWebSocket();
    connectTikfinityFallback();
    await pollKickChat();
    setInterval(pollKickChat,900);

    /*
      Sincroniza ranking por si ranking.html hace un reset manual.
    */
    setInterval(loadLeaderboard, 15000);
}

start();

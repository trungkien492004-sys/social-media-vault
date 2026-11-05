// Social Media Vault Frontend Logic

let currentPlatformFilter = "all";
let currentSearchQuery = "";
let currentVaultDetail = null;
let currentMediaFilter = "all";
let activeEventSource = null;

let currentUser = null;
let authMode = "login";

// Any 401 from the API means the session expired: show the login screen again
const _origFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
    const res = await _origFetch(...args);
    const url = String(args[0] && args[0].url ? args[0].url : args[0]);
    if (res.status === 401 && !url.includes("/api/auth/")) {
        currentUser = null;
        showAuthModal();
    }
    return res;
};

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", async () => {
    initLucide();
    setupEventListeners();
    setupAuthListeners();
    await initAuth();
});

async function initAuth() {
    try {
        const res = await fetch("/api/auth/me");
        if (res.ok) {
            onLoggedIn(await res.json());
            return;
        }
    } catch (e) {
        console.error("Không kiểm tra được đăng nhập:", e);
    }
    showAuthModal();
}

function onLoggedIn(user) {
    currentUser = user;
    document.getElementById("authModal").classList.add("hidden");
    document.getElementById("userBar").classList.remove("hidden");
    document.getElementById("userBar").classList.add("flex");
    document.getElementById("userEmailLabel").textContent = user.email;
    document.getElementById("btnOpenAdmin").classList.toggle("hidden", !user.is_admin);
    loadStats();
    loadVaults();
    checkCookieStatus();
    initLucide();
}

async function showAuthModal() {
    document.getElementById("authModal").classList.remove("hidden");
    document.getElementById("userBar").classList.add("hidden");
    document.getElementById("userBar").classList.remove("flex");
    try {
        const cfg = await (await _origFetch("/api/auth/config")).json();
        document.getElementById("authInvite").classList.toggle("hidden", !cfg.invite_required || authMode !== "register");
        document.getElementById("tabRegister").classList.toggle("hidden", !cfg.registration_open);
    } catch (e) { /* ignore */ }
    initLucide();
}

function setAuthMode(mode) {
    authMode = mode;
    const isLogin = mode === "login";
    document.getElementById("tabLogin").className = `py-2 rounded-lg transition ${isLogin ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"}`;
    document.getElementById("tabRegister").className = `py-2 rounded-lg transition ${!isLogin ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"}`;
    document.getElementById("authSubmit").textContent = isLogin ? "Đăng nhập" : "Tạo tài khoản";
    document.getElementById("authSubtitle").textContent = isLogin
        ? "Đăng nhập để dùng kho riêng của bạn"
        : "Tạo tài khoản mới (người đăng ký đầu tiên là quản trị viên)";
    document.getElementById("authPassword").setAttribute("autocomplete", isLogin ? "current-password" : "new-password");
    document.getElementById("authError").classList.add("hidden");
    showAuthModal();
}

function setupAuthListeners() {
    document.getElementById("tabLogin").addEventListener("click", () => setAuthMode("login"));
    document.getElementById("tabRegister").addEventListener("click", () => setAuthMode("register"));

    document.getElementById("authForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const errEl = document.getElementById("authError");
        const btn = document.getElementById("authSubmit");
        errEl.classList.add("hidden");
        btn.disabled = true;
        try {
            const res = await _origFetch(`/api/auth/${authMode}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    email: document.getElementById("authEmail").value,
                    password: document.getElementById("authPassword").value,
                    invite_code: document.getElementById("authInvite").value || null
                })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join("; ") : data.detail;
                throw new Error(detail || "Không thể đăng nhập");
            }
            document.getElementById("authPassword").value = "";
            onLoggedIn(data);
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove("hidden");
        } finally {
            btn.disabled = false;
        }
    });

    document.getElementById("btnLogout").addEventListener("click", async () => {
        await _origFetch("/api/auth/logout", { method: "POST" });
        currentUser = null;
        document.getElementById("vaultsGrid").innerHTML = "";
        document.getElementById("progressList").innerHTML = "";
        document.getElementById("progressSection").classList.add("hidden");
        Object.keys(taskCards).forEach(k => delete taskCards[k]);
        setAuthMode("login");
    });

    // Admin panel
    document.getElementById("btnOpenAdmin").addEventListener("click", openAdminPanel);
    document.getElementById("adminBtnClose").addEventListener("click", () => document.getElementById("adminModal").classList.add("hidden"));
    document.getElementById("adminModal").addEventListener("click", (e) => {
        if (e.target.id === "adminModal") e.target.classList.add("hidden");
    });
    document.getElementById("adminBtnBack").addEventListener("click", showAdminUsers);
}

// ---------------- Admin panel ----------------
async function openAdminPanel() {
    document.getElementById("adminModal").classList.remove("hidden");
    showAdminUsers();
    try {
        const ov = await (await fetch("/api/admin/overview")).json();
        document.getElementById("adminOverview").innerHTML = [
            ["Người dùng", ov.users], ["Kho", ov.vaults], ["File", ov.items], ["Dung lượng", formatBytes(ov.size_bytes)]
        ].map(([label, val]) => `
            <div class="bg-slate-800/60 rounded-xl px-3 py-2">
                <div class="text-slate-400">${label}</div>
                <div class="text-base font-bold text-white">${val}</div>
            </div>`).join("");
    } catch (e) { /* ignore */ }
}

async function showAdminUsers() {
    document.getElementById("adminVaultsView").classList.add("hidden");
    document.getElementById("adminUsersView").classList.remove("hidden");
    const body = document.getElementById("adminUsersBody");
    body.innerHTML = `<tr><td colspan="6" class="px-3 py-6 text-center text-slate-500">Đang tải...</td></tr>`;

    const res = await fetch("/api/admin/users");
    if (!res.ok) { body.innerHTML = ""; showToast("Không tải được danh sách người dùng", "error"); return; }
    const users = await res.json();

    body.innerHTML = "";
    users.forEach(u => {
        const tr = document.createElement("tr");
        tr.className = u.is_disabled ? "opacity-50" : "";
        const isSelf = currentUser && u.id === currentUser.id;
        tr.innerHTML = `
            <td class="px-3 py-2.5 text-slate-200">
                ${escapeHtml(u.email)}
                ${u.is_admin ? '<span class="ml-1 text-[10px] bg-violet-600/30 text-violet-200 px-1.5 py-0.5 rounded">Admin</span>' : ""}
                ${u.is_disabled ? '<span class="ml-1 text-[10px] bg-rose-600/30 text-rose-200 px-1.5 py-0.5 rounded">Đã khóa</span>' : ""}
            </td>
            <td class="px-3 py-2.5 text-slate-300">${u.vault_count}</td>
            <td class="px-3 py-2.5 text-slate-300">${u.item_count}</td>
            <td class="px-3 py-2.5 text-slate-300">${formatBytes(u.size_bytes)}</td>
            <td class="px-3 py-2.5 text-slate-400">${formatDate(u.created_at)}</td>
            <td class="px-3 py-2.5 text-right whitespace-nowrap space-x-1">
                <button class="btn-view px-2.5 py-1 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 text-white">Xem kho</button>
                ${isSelf ? "" : `
                <button class="btn-toggle px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200">${u.is_disabled ? "Mở khóa" : "Khóa"}</button>
                <button class="btn-del px-2.5 py-1 rounded-lg bg-rose-900/40 hover:bg-rose-900/60 text-rose-300">Xóa</button>`}
            </td>`;
        tr.querySelector(".btn-view").addEventListener("click", () => showAdminUserVaults(u));
        const tg = tr.querySelector(".btn-toggle");
        if (tg) tg.addEventListener("click", async () => {
            const r = await fetch(`/api/admin/users/${u.id}/toggle-disabled`, { method: "POST" });
            if (r.ok) showAdminUsers(); else showToast("Không thực hiện được", "error");
        });
        const del = tr.querySelector(".btn-del");
        if (del) del.addEventListener("click", async () => {
            if (!confirm(`Xóa tài khoản ${u.email} và TOÀN BỘ kho của họ? Không thể hoàn tác.`)) return;
            const r = await fetch(`/api/admin/users/${u.id}`, { method: "DELETE" });
            if (r.ok) { showToast("Đã xóa tài khoản", "success"); showAdminUsers(); } else showToast("Không xóa được", "error");
        });
        body.appendChild(tr);
    });
    initLucide();
}

async function showAdminUserVaults(user) {
    document.getElementById("adminUsersView").classList.add("hidden");
    document.getElementById("adminVaultsView").classList.remove("hidden");
    document.getElementById("adminVaultsTitle").textContent = `Kho của ${user.email}`;
    const grid = document.getElementById("adminVaultsGrid");
    grid.innerHTML = `<p class="text-xs text-slate-500">Đang tải...</p>`;

    const res = await fetch(`/api/admin/users/${user.id}/vaults`);
    if (!res.ok) { grid.innerHTML = ""; showToast("Không tải được kho của người dùng", "error"); return; }
    const vaults = await res.json();
    grid.innerHTML = vaults.length ? "" : `<p class="text-xs text-slate-500 col-span-full">Người dùng này chưa có kho nào.</p>`;

    vaults.forEach(v => {
        const pConf = PLATFORM_CONFIG[v.platform] || PLATFORM_CONFIG.other;
        const card = document.createElement("div");
        card.className = "bg-slate-800/60 border border-slate-700/60 rounded-xl p-4 space-y-2";
        card.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-[10px] font-bold px-2 py-0.5 rounded uppercase border ${pConf.color}">${pConf.name}</span>
                <span class="text-[10px] text-slate-500">${formatDate(v.created_at)}</span>
            </div>
            <h5 class="text-sm font-bold text-white truncate" title="${escapeHtml(v.custom_name)}">${escapeHtml(v.custom_name)}</h5>
            <p class="text-[11px] text-slate-400 truncate" title="${escapeHtml(v.profile_url)}">${escapeHtml(v.profile_url)}</p>
            <div class="flex items-center justify-between text-xs text-slate-300">
                <span>${v.total_images || 0} ảnh • ${v.total_videos || 0} video</span>
                <span>${formatBytes(v.total_size_bytes)}</span>
            </div>
            <div class="flex gap-2 pt-1">
                <button class="btn-open flex-1 bg-indigo-600/90 hover:bg-indigo-600 text-white text-xs font-semibold py-1.5 rounded-lg">Xem thư viện</button>
                <button class="btn-zip px-2.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-emerald-300 text-xs">ZIP</button>
                <button class="btn-delete px-2.5 rounded-lg bg-rose-900/40 hover:bg-rose-900/60 text-rose-300 text-xs">Xóa</button>
            </div>`;
        card.querySelector(".btn-open").addEventListener("click", () => openGalleryModal(v.id));
        card.querySelector(".btn-zip").addEventListener("click", () => triggerZipDownload(v.id));
        card.querySelector(".btn-delete").addEventListener("click", async () => {
            if (!confirm(`Xóa kho "${v.custom_name}" của ${user.email}?`)) return;
            const r = await fetch(`/api/vaults/${v.id}`, { method: "DELETE" });
            if (r.ok) { showToast("Đã xóa kho", "success"); showAdminUserVaults(user); } else showToast("Không xóa được", "error");
        });
        grid.appendChild(card);
    });
}

function initLucide() {
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

// Format bytes into readable format (MB, GB, etc.)
function formatBytes(bytes, decimals = 1) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Format ISO date to readable string
function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Platform badge metadata
const PLATFORM_CONFIG = {
    tiktok: {
        name: 'TikTok',
        color: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
        icon: 'video'
    },
    instagram: {
        name: 'Instagram',
        color: 'bg-pink-500/10 text-pink-400 border-pink-500/30',
        icon: 'camera'
    },
    threads: {
        name: 'Threads',
        color: 'bg-violet-500/10 text-violet-300 border-violet-500/30',
        icon: 'message-circle'
    },
    facebook: {
        name: 'Facebook',
        color: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
        icon: 'facebook'
    },
    zalo: {
        name: 'Zalo',
        color: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
        icon: 'message-square'
    },
    other: {
        name: 'Media',
        color: 'bg-slate-700 text-slate-300 border-slate-600',
        icon: 'link'
    }
};

// Public storage URL when available (Supabase), otherwise the locally served file
function mediaUrl(item) {
    return item.file_url || `/vault/${encodeURI(item.file_path)}`;
}

function escapeHtml(str) {
    return String(str ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
}

// Split textarea content into a de-duplicated list of links (one per line / whitespace)
function parseUrlLines(text) {
    const seen = new Set();
    return (text || "").split(/[\s,]+/).map(s => s.trim()).filter(s => {
        if (!s || seen.has(s)) return false;
        seen.add(s);
        return true;
    });
}

function detectPlatformFromUrl(url) {
    const lower = url.toLowerCase();
    if (lower.includes("tiktok.com")) return "tiktok";
    if (lower.includes("instagram.com")) return "instagram";
    if (lower.includes("threads.net")) return "threads";
    if (lower.includes("facebook.com") || lower.includes("fb.watch") || lower.includes("fb.com")) return "facebook";
    if (lower.includes("zalo.me") || lower.includes("zadn.vn")) return "zalo";
    return "other";
}

// Setup Event Listeners
function setupEventListeners() {
    // 1. URL input typing auto-detection
    const urlInput = document.getElementById("urlInput");
    const detectedBadge = document.getElementById("detectedPlatformBadge");

    urlInput.addEventListener("input", (e) => {
        const lines = parseUrlLines(e.target.value);
        const val = lines[0] || "";
        const hint = document.getElementById("linkCountHint");
        if (hint) {
            hint.textContent = lines.length > 1
                ? `Đã nhận ${lines.length} link - sẽ tải song song tối đa 3 link cùng lúc.`
                : "Mỗi dòng một link: hệ thống tải song song tối đa 3 link cùng lúc.";
        }
        if (val.length > 5) {
            const platform = detectPlatformFromUrl(val);
            if (platform !== "other") {
                const conf = PLATFORM_CONFIG[platform];
                detectedBadge.textContent = conf.name;
                detectedBadge.className = `absolute right-3 text-[11px] font-semibold px-2.5 py-1 rounded-md uppercase tracking-wider border ${conf.color}`;
                detectedBadge.classList.remove("hidden");
            } else {
                detectedBadge.classList.add("hidden");
            }
        } else {
            detectedBadge.classList.add("hidden");
        }
    });

    // 2. Extraction Form Submit
    const extractForm = document.getElementById("extractForm");
    extractForm.addEventListener("submit", handleExtractSubmit);

    // 3. Platform Filters
    document.querySelectorAll(".platform-filter").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".platform-filter").forEach(b => {
                b.classList.remove("active", "bg-indigo-600", "text-white");
                b.classList.add("bg-slate-800", "text-slate-400");
            });
            btn.classList.add("active", "bg-indigo-600", "text-white");
            btn.classList.remove("bg-slate-800", "text-slate-400");

            currentPlatformFilter = btn.dataset.filter;
            loadVaults();
        });
    });

    // 4. Search input
    let searchTimeout;
    const searchInput = document.getElementById("searchInput");
    searchInput.addEventListener("input", (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentSearchQuery = e.target.value.trim();
            loadVaults();
        }, 300);
    });

    // 5. Gallery Modal Events
    document.getElementById("modalBtnClose").addEventListener("click", closeGalleryModal);
    document.getElementById("galleryModal").addEventListener("click", (e) => {
        if (e.target.id === "galleryModal") closeGalleryModal();
    });

    // Gallery Filter Tabs
    document.querySelectorAll(".media-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".media-tab").forEach(t => {
                t.classList.remove("active", "bg-indigo-600", "text-white");
                t.classList.add("bg-slate-800", "text-slate-400");
            });
            tab.classList.add("active", "bg-indigo-600", "text-white");
            tab.classList.remove("bg-slate-800", "text-slate-400");

            currentMediaFilter = tab.dataset.mediaTab;
            renderModalMedia();
        });
    });

    // Modal Download ZIP Button
    document.getElementById("modalBtnDownloadZip").addEventListener("click", () => {
        if (currentVaultDetail) {
            triggerZipDownload(currentVaultDetail.id);
        }
    });

    // 6. Lightbox Modal Events
    document.getElementById("lightboxBtnClose").addEventListener("click", closeLightbox);
    document.getElementById("lightboxModal").addEventListener("click", (e) => {
        if (e.target.id === "lightboxModal") closeLightbox();
    });
    document.getElementById("lightboxBtnPrev").addEventListener("click", () => stepLightbox(-1));
    document.getElementById("lightboxBtnNext").addEventListener("click", () => stepLightbox(1));
    document.addEventListener("keydown", (e) => {
        const open = !document.getElementById("lightboxModal").classList.contains("hidden");
        if (!open) return;
        if (e.key === "ArrowLeft") stepLightbox(-1);
        else if (e.key === "ArrowRight") stepLightbox(1);
        else if (e.key === "Escape") closeLightbox();
    });
    // Swipe left/right on touch screens
    let touchStartX = null;
    const lbContent = document.getElementById("lightboxContent");
    lbContent.addEventListener("touchstart", (e) => { touchStartX = e.changedTouches[0].clientX; }, { passive: true });
    lbContent.addEventListener("touchend", (e) => {
        if (touchStartX === null) return;
        const dx = e.changedTouches[0].clientX - touchStartX;
        touchStartX = null;
        if (Math.abs(dx) > 60) stepLightbox(dx < 0 ? 1 : -1);
    }, { passive: true });
    document.getElementById("btnClearFinished").addEventListener("click", clearFinishedProgress);

    // 7. Settings Modal Events
    document.getElementById("btnOpenSettings").addEventListener("click", openSettingsModal);
    document.getElementById("settingsBtnClose").addEventListener("click", closeSettingsModal);
    document.getElementById("settingsModal").addEventListener("click", (e) => {
        if (e.target.id === "settingsModal") closeSettingsModal();
    });

    // Cookie file select
    const cookieFileInput = document.getElementById("cookieFileInput");
    cookieFileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            document.getElementById("cookieFileName").textContent = `Đã chọn: ${e.target.files[0].name}`;
        }
    });

    // Cookie upload form
    document.getElementById("cookieUploadForm").addEventListener("submit", handleCookieUpload);
    document.getElementById("btnDeleteCookie").addEventListener("click", handleCookieDelete);
}

// Load Global Stats
async function loadStats() {
    try {
        const res = await fetch("/api/vaults/stats");
        if (res.ok) {
            const data = await res.json();
            document.getElementById("statVaults").textContent = data.total_vaults || 0;
            document.getElementById("statMedia").textContent = data.total_items || 0;
            document.getElementById("statStorage").textContent = formatBytes(data.total_size_bytes || 0);
        }
    } catch (e) {
        console.error("Lỗi khi tải thống kê:", e);
    }
}

// Load Vaults List
async function loadVaults() {
    const grid = document.getElementById("vaultsGrid");
    const emptyState = document.getElementById("emptyState");

    let url = `/api/vaults?platform=${currentPlatformFilter}`;
    if (currentSearchQuery) {
        url += `&search=${encodeURIComponent(currentSearchQuery)}`;
    }

    try {
        const res = await fetch(url);
        if (res.ok) {
            const vaults = await res.json();
            grid.innerHTML = "";

            if (vaults.length === 0) {
                emptyState.classList.remove("hidden");
                grid.classList.add("hidden");
                return;
            }

            emptyState.classList.add("hidden");
            grid.classList.remove("hidden");

            vaults.forEach(vault => {
                grid.appendChild(createVaultCard(vault));
            });

            initLucide();
        }
    } catch (e) {
        console.error("Lỗi tải danh sách kho:", e);
        showToast("Không thể kết nối đến máy chủ", "error");
    }
}

// Create a single Vault Card Element
function createVaultCard(vault) {
    const pConf = PLATFORM_CONFIG[vault.platform] || PLATFORM_CONFIG.other;
    const card = document.createElement("div");
    card.className = "glass-panel rounded-2xl p-5 hover:border-slate-700 transition flex flex-col justify-between group shadow-lg";

    card.innerHTML = `
        <div class="space-y-3">
            <div class="flex items-center justify-between">
                <span class="text-[11px] font-bold px-2.5 py-1 rounded-md uppercase tracking-wider border ${pConf.color}">
                    ${pConf.name}
                </span>
                <span class="text-[11px] text-slate-500">${formatDate(vault.created_at)}</span>
            </div>

            <div>
                <h4 class="text-base font-bold text-white group-hover:text-indigo-400 transition truncate" title="${escapeHtml(vault.custom_name)}">
                    ${escapeHtml(vault.custom_name)}
                </h4>
                <p class="text-xs text-slate-400 mt-1 line-clamp-2 min-h-[2rem]">
                    ${vault.notes ? escapeHtml(vault.notes) : '<span class="italic text-slate-600">Không có ghi chú</span>'}
                </p>
            </div>

            ${vault.status === "error" ? `<p class="text-[11px] text-rose-300 line-clamp-2">${escapeHtml(vault.error_message || "Tải lỗi")}</p>` : ""}
            ${vault.status === "pending" || vault.status === "downloading" ? `<p class="text-[11px] text-amber-300">Chưa hoàn tất - bấm nút tải lại nếu bị treo</p>` : ""}

            <!-- Stats Bar -->
            <div class="flex items-center justify-between py-2.5 px-3 bg-slate-900/80 rounded-xl text-xs border border-slate-800">
                <div class="flex items-center space-x-3 text-slate-300">
                    <span class="flex items-center space-x-1" title="Số ảnh">
                        <i data-lucide="image" class="w-3.5 h-3.5 text-indigo-400"></i>
                        <span>${vault.total_images || 0}</span>
                    </span>
                    <span class="flex items-center space-x-1" title="Số video">
                        <i data-lucide="video" class="w-3.5 h-3.5 text-violet-400"></i>
                        <span>${vault.total_videos || 0}</span>
                    </span>
                </div>
                <div class="text-slate-400 font-medium">
                    ${formatBytes(vault.total_size_bytes)}
                </div>
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="pt-4 mt-4 border-t border-slate-800/80 flex items-center justify-between gap-2">
            <button class="btn-open-gallery flex-1 flex items-center justify-center space-x-1.5 bg-indigo-600/90 hover:bg-indigo-600 text-white text-xs font-semibold py-2 rounded-xl transition shadow">
                <i data-lucide="layout-grid" class="w-3.5 h-3.5"></i>
                <span>Xem Thư Viện</span>
            </button>
            ${vault.status !== "completed" || !vault.total_items ? `
            <button class="btn-retry-vault p-2 rounded-xl bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 transition border border-amber-500/40" title="Tải lại">
                <i data-lucide="refresh-cw" class="w-4 h-4"></i>
            </button>` : ""}
            <button class="btn-download-zip p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 transition border border-slate-700/60" title="Tải file .ZIP">
                <i data-lucide="file-archive" class="w-4 h-4 text-emerald-400"></i>
            </button>
            <button class="btn-delete-vault p-2 rounded-xl bg-slate-800 hover:bg-rose-900/40 text-slate-400 hover:text-rose-400 transition border border-slate-700/60" title="Xóa kho">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
            </button>
        </div>
    `;

    // Attach card action listeners
    card.querySelector(".btn-open-gallery").addEventListener("click", () => openGalleryModal(vault.id));
    const retryBtn = card.querySelector(".btn-retry-vault");
    if (retryBtn) retryBtn.addEventListener("click", () => retryVault(vault));
    card.querySelector(".btn-download-zip").addEventListener("click", () => triggerZipDownload(vault.id));
    card.querySelector(".btn-delete-vault").addEventListener("click", () => handleDeleteVault(vault.id, vault.custom_name));

    return card;
}

// Handle Form Submit & Start Extraction (one or many links)
async function handleExtractSubmit(e) {
    e.preventDefault();

    const urls = parseUrlLines(document.getElementById("urlInput").value);
    const customName = document.getElementById("customNameInput").value.trim();
    const notes = document.getElementById("notesInput").value.trim();
    const mediaType = document.querySelector('input[name="mediaType"]:checked').value;
    const maxItems = parseInt(document.getElementById("maxItemsSelect")?.value || "50", 10);

    if (urls.length === 0) {
        showToast("Vui lòng dán ít nhất một liên kết", "error");
        return;
    }

    const btnSubmit = document.getElementById("btnSubmit");
    btnSubmit.disabled = true;

    if (!(await confirmDuplicates(urls))) {
        btnSubmit.disabled = false;
        return;
    }

    try {
        const res = await fetch("/api/tasks/start-batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                urls: urls,
                custom_name: customName || null,
                notes: notes || null,
                media_type: mediaType,
                max_items: maxItems
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            const detail = Array.isArray(err.detail) ? err.detail.map(d => d.msg).join("; ") : err.detail;
            throw new Error(detail || "Không thể khởi tạo tác vụ");
        }

        const data = await res.json();
        showToast(`Bắt đầu tải ${data.tasks.length} liên kết...`, "info");

        // Clear input form
        document.getElementById("urlInput").value = "";
        document.getElementById("customNameInput").value = "";
        document.getElementById("notesInput").value = "";
        document.getElementById("detectedPlatformBadge").classList.add("hidden");

        startBatchStream(data.tasks, urls, customName);
    } catch (err) {
        showToast(err.message, "error");
    } finally {
        btnSubmit.disabled = false;
    }
}

// ---- Progress cards (one per task) + a single multiplexed SSE connection ----
const taskCards = {}; // task_id -> { el, done }

function createProgressCard(taskId, label) {
    const el = document.createElement("div");
    el.className = "glass-panel border border-indigo-500/30 rounded-2xl p-5 shadow-xl space-y-3";
    el.innerHTML = `
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div class="flex items-center space-x-3 min-w-0">
                <div class="task-spinner w-8 h-8 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center shrink-0">
                    <i data-lucide="loader-2" class="w-5 h-5 animate-spin"></i>
                </div>
                <div class="min-w-0">
                    <h4 class="task-title font-bold text-sm text-white truncate"></h4>
                    <p class="task-message text-xs text-slate-400">Đang chờ đến lượt xử lý...</p>
                </div>
            </div>
            <div class="flex items-center space-x-2 shrink-0">
                <span class="task-count text-xs bg-slate-800 text-indigo-300 px-3 py-1 rounded-full font-medium border border-slate-700">0/0</span>
                <span class="task-percent text-xs font-bold text-white bg-indigo-600 px-2.5 py-1 rounded-full">0%</span>
            </div>
        </div>
        <div class="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
            <div class="task-bar bg-gradient-to-r from-indigo-500 to-emerald-400 h-2 rounded-full transition-all duration-300" style="width:0%"></div>
        </div>
        <div class="task-feed hidden pt-2 border-t border-slate-800">
            <div class="task-feed-list flex items-center space-x-2 overflow-x-auto pb-1"></div>
        </div>
    `;
    el.querySelector(".task-title").textContent = label;
    return el;
}

function startBatchStream(tasks, urls, customName) {
    // Previous batches keep their own stream open so they keep reporting progress

    const section = document.getElementById("progressSection");
    const list = document.getElementById("progressList");
    section.classList.remove("hidden");

    tasks.forEach((t, i) => {
        const label = customName
            ? (tasks.length > 1 ? `${customName} ${i + 1}` : customName)
            : (urls[i] || `Tác vụ ${i + 1}`);
        const el = createProgressCard(t.task_id, label);
        list.prepend(el);
        taskCards[t.task_id] = { el, done: false, vaultId: t.vault_id, label };
    });
    initLucide();

    const ids = tasks.map(t => t.task_id).join(",");
    const es = new EventSource(`/api/tasks/stream-multi?ids=${ids}`);
    activeEventSource = es;

    es.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (err) {
            return;
        }

        if (data.status === "batch_done") {
            es.close();
            loadStats();
            loadVaults();
            return;
        }
        updateProgressCard(data);
    };

    es.onerror = () => {
        // Server closes the stream when everything is finished; just stop retrying.
        es.close();
        const pending = Object.values(taskCards).some(c => !c.done);
        if (pending) {
            showToast("Mất kết nối theo dõi tiến trình. Tải lại danh sách kho để xem kết quả.", "error");
            loadVaults();
        }
    };
}

function updateProgressCard(data) {
    const card = taskCards[data.task_id];
    if (!card) return;
    const el = card.el;

    if (data.message) el.querySelector(".task-message").textContent = data.message;

    if (data.progress !== undefined) {
        const percent = Math.min(100, Math.max(0, data.progress));
        el.querySelector(".task-bar").style.width = `${percent}%`;
        el.querySelector(".task-percent").textContent = `${percent}%`;
    }

    if (data.total > 0) {
        el.querySelector(".task-count").textContent = `${data.current || 0}/${data.total}`;
    }

    if (data.latest_item) {
        const item = data.latest_item;
        const feed = el.querySelector(".task-feed");
        feed.classList.remove("hidden");
        const mini = document.createElement("div");
        mini.className = "w-14 h-14 rounded-lg bg-slate-800 overflow-hidden shrink-0 border border-slate-700 relative flex items-center justify-center";
        const src = mediaUrl(item);
        if (item.file_type === "image") {
            mini.innerHTML = `<img src="${src}" class="w-full h-full object-cover" />`;
        } else {
            mini.innerHTML = `
                <video src="${src}#t=0.1" preload="metadata" muted class="w-full h-full object-cover"></video>
                <div class="absolute inset-0 bg-black/40 flex items-center justify-center">
                    <i data-lucide="play" class="w-4 h-4 text-white"></i>
                </div>`;
        }
        el.querySelector(".task-feed-list").prepend(mini);
        initLucide();
    }

    if (data.status === "completed") {
        card.done = true;
        el.querySelector(".task-spinner").innerHTML = `<i data-lucide="check-circle" class="w-5 h-5 text-emerald-400"></i>`;
        el.classList.remove("border-indigo-500/30");
        el.classList.add("border-emerald-500/40");
        showToast(data.message || "Đã trích xuất & lưu trữ thành công!", "success");
        loadStats();
        loadVaults();
        initLucide();
    } else if (data.status === "error") {
        card.done = true;
        el.querySelector(".task-spinner").innerHTML = `<i data-lucide="alert-circle" class="w-5 h-5 text-rose-400"></i>`;
        el.querySelector(".task-bar").className = "task-bar bg-rose-600 h-2 rounded-full";
        el.classList.remove("border-indigo-500/30");
        el.classList.add("border-rose-500/40");
        showToast(data.message || "Đã xảy ra lỗi khi cào media", "error");
        if (card.vaultId && !el.querySelector(".task-retry")) {
            const btn = document.createElement("button");
            btn.className = "task-retry mt-1 inline-flex items-center space-x-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border border-amber-500/40 transition";
            btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Tải lại</span>`;
            btn.addEventListener("click", () => {
                btn.disabled = true;
                retryVault({ id: card.vaultId, custom_name: card.label });
            });
            el.appendChild(btn);
        }
        loadVaults();
        initLucide();
    }
}

function clearFinishedProgress() {
    Object.entries(taskCards).forEach(([id, c]) => {
        if (c.done) {
            c.el.remove();
            delete taskCards[id];
        }
    });
    if (Object.keys(taskCards).length === 0) {
        document.getElementById("progressSection").classList.add("hidden");
    }
}

// Open Gallery Modal
async function openGalleryModal(vaultId) {
    const modal = document.getElementById("galleryModal");
    modal.classList.remove("hidden");

    try {
        const res = await fetch(`/api/vaults/${vaultId}`);
        if (!res.ok) throw new Error("Không thể tải thông tin kho");
        
        currentVaultDetail = await res.json();
        
        // Populate Header
        const pConf = PLATFORM_CONFIG[currentVaultDetail.platform] || PLATFORM_CONFIG.other;
        const pBadge = document.getElementById("modalPlatformBadge");
        pBadge.textContent = pConf.name;
        pBadge.className = `text-[10px] font-bold px-2 py-0.5 rounded uppercase border ${pConf.color}`;
        
        document.getElementById("modalVaultName").textContent = currentVaultDetail.custom_name;
        document.getElementById("modalVaultNotes").textContent = currentVaultDetail.notes || "Không có ghi chú";
        
        // Counts
        document.getElementById("modalCountAll").textContent = currentVaultDetail.total_items || 0;
        document.getElementById("modalCountImg").textContent = currentVaultDetail.total_images || 0;
        document.getElementById("modalCountVid").textContent = currentVaultDetail.total_videos || 0;
        document.getElementById("modalTotalSize").textContent = formatBytes(currentVaultDetail.total_size_bytes);

        // Reset filter tab to "all"
        currentMediaFilter = "all";
        document.querySelectorAll(".media-tab").forEach(t => {
            if (t.dataset.mediaTab === "all") {
                t.classList.add("active", "bg-indigo-600", "text-white");
                t.classList.remove("bg-slate-800", "text-slate-400");
            } else {
                t.classList.remove("active", "bg-indigo-600", "text-white");
                t.classList.add("bg-slate-800", "text-slate-400");
            }
        });

        renderModalMedia();
    } catch (e) {
        showToast(e.message, "error");
        closeGalleryModal();
    }
}

function closeGalleryModal() {
    document.getElementById("galleryModal").classList.add("hidden");
    currentVaultDetail = null;
}

// Render Media inside Modal Grid
function renderModalMedia() {
    if (!currentVaultDetail) return;
    const grid = document.getElementById("modalMediaGrid");
    grid.innerHTML = "";

    let items = currentVaultDetail.media_items || [];
    if (currentMediaFilter !== "all") {
        items = items.filter(i => i.file_type === currentMediaFilter);
    }

    if (items.length === 0) {
        grid.innerHTML = `<div class="col-span-full py-12 text-center text-xs text-slate-500">Không có tệp tin nào trong mục này</div>`;
        return;
    }

    items.forEach(item => {
        const itemEl = document.createElement("div");
        itemEl.className = "group relative aspect-square rounded-xl bg-slate-800/80 overflow-hidden border border-slate-700/60 cursor-pointer shadow hover:border-indigo-500 transition";

        const filePath = mediaUrl(item);

        if (item.file_type === "image") {
            itemEl.innerHTML = `
                <img src="${filePath}" loading="lazy" class="w-full h-full object-cover group-hover:scale-105 transition duration-300" />
                <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent opacity-0 group-hover:opacity-100 transition p-2.5 flex flex-col justify-between">
                    <span class="self-end text-[10px] bg-indigo-600/90 text-white font-semibold px-2 py-0.5 rounded">Ảnh</span>
                    <p class="text-[11px] text-white truncate">${escapeHtml(item.caption || item.file_name)}</p>
                </div>
            `;
        } else {
            itemEl.innerHTML = `
                <video src="${filePath}#t=0.1" preload="metadata" muted class="w-full h-full object-cover"></video>
                <div class="absolute inset-0 bg-black/30 flex items-center justify-center group-hover:bg-black/50 transition">
                    <div class="w-10 h-10 rounded-full bg-white/20 backdrop-blur-md flex items-center justify-center text-white group-hover:scale-110 transition">
                        <i data-lucide="play" class="w-5 h-5 fill-white"></i>
                    </div>
                </div>
                <div class="absolute bottom-2 left-2 right-2 flex items-center justify-between text-[10px] text-white">
                    <span class="bg-violet-600/90 font-semibold px-2 py-0.5 rounded">Video</span>
                    <span class="bg-black/60 px-1.5 py-0.5 rounded">${formatBytes(item.file_size)}</span>
                </div>
            `;
        }

        itemEl.addEventListener("click", () => openLightbox(item, items));
        grid.appendChild(itemEl);
    });

    initLucide();
}

// Lightbox Preview (HD Photo or Video Player) with prev/next browsing like a collection
let lightboxItems = [];
let lightboxIndex = 0;

function openLightbox(item, items) {
    lightboxItems = items && items.length ? items : [item];
    lightboxIndex = Math.max(0, lightboxItems.findIndex(i => i.id === item.id));
    renderLightbox();
    document.getElementById("lightboxModal").classList.remove("hidden");
}

function stepLightbox(delta) {
    if (lightboxItems.length < 2) return;
    lightboxIndex = (lightboxIndex + delta + lightboxItems.length) % lightboxItems.length;
    renderLightbox();
}

function renderLightbox() {
    const item = lightboxItems[lightboxIndex];
    if (!item) return;

    const container = document.getElementById("lightboxContent");
    const captionEl = document.getElementById("lightboxCaption");
    const btnDownload = document.getElementById("lightboxBtnDownload");
    const counter = document.getElementById("lightboxCounter");
    const filePath = mediaUrl(item);

    // Stop any previous video before replacing the content
    const prev = container.querySelector("video");
    if (prev) { prev.pause(); prev.removeAttribute("src"); prev.load(); }

    captionEl.textContent = item.caption || item.file_name;
    btnDownload.href = item.file_url ? `${item.file_url}?download=${encodeURIComponent(item.file_name)}` : filePath;
    btnDownload.setAttribute("download", item.file_name);
    counter.textContent = `${lightboxIndex + 1} / ${lightboxItems.length}`;

    const multi = lightboxItems.length > 1;
    document.getElementById("lightboxBtnPrev").classList.toggle("hidden", !multi);
    document.getElementById("lightboxBtnNext").classList.toggle("hidden", !multi);

    if (item.file_type === "image") {
        container.innerHTML = `<img src="${filePath}" class="max-h-[75vh] w-auto max-w-full rounded-lg object-contain shadow-2xl" />`;
    } else {
        container.innerHTML = `
            <video src="${filePath}" controls autoplay playsinline class="max-h-[75vh] w-auto max-w-full rounded-lg shadow-2xl">
                Trình duyệt của bạn không hỗ trợ thẻ video.
            </video>`;
        const video = container.querySelector("video");
        video.addEventListener("ended", () => {
            if (document.getElementById("lightboxAutoNext").checked && lightboxItems.length > 1) {
                stepLightbox(1);
            }
        });
        // Autoplay with sound may be blocked after auto-advance; fall back to muted playback
        const p = video.play();
        if (p && p.catch) {
            p.catch(() => { video.muted = true; video.play().catch(() => {}); });
        }
    }
    initLucide();
}

function closeLightbox() {
    const modal = document.getElementById("lightboxModal");
    const container = document.getElementById("lightboxContent");
    const video = container.querySelector("video");
    if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
    container.innerHTML = "";
    modal.classList.add("hidden");
}

// Download Vault ZIP Archive
function triggerZipDownload(vaultId) {
    showToast("Đang chuẩn bị gói nén .ZIP, vui lòng đợi giây lát...", "info");
    window.location.href = `/api/vaults/${vaultId}/download-zip`;
}

// Delete Vault
async function handleDeleteVault(vaultId, name) {
    if (!confirm(`Bạn có chắc chắn muốn xóa vĩnh viễn kho "${name}" và toàn bộ media đã tải về không?`)) {
        return;
    }

    try {
        const res = await fetch(`/api/vaults/${vaultId}`, { method: "DELETE" });
        if (res.ok) {
            showToast(`Đã xóa thành công kho "${name}"`, "success");
            loadStats();
            loadVaults();
        } else {
            throw new Error("Không thể xóa kho lưu trữ");
        }
    } catch (e) {
        showToast(e.message, "error");
    }
}

// Settings & Cookies Manager
function openSettingsModal() {
    document.getElementById("settingsModal").classList.remove("hidden");
    checkCookieStatus();
}

function closeSettingsModal() {
    document.getElementById("settingsModal").classList.add("hidden");
}

async function checkCookieStatus() {
    try {
        const res = await fetch("/api/settings/cookies");
        if (res.ok) {
            const data = await res.json();
            const badge = document.getElementById("cookieStatusBadge");
            const title = document.getElementById("cookieStatusTitle");
            const details = document.getElementById("cookieStatusDetails");
            const btnDel = document.getElementById("btnDeleteCookie");

            if (data.exists) {
                badge.textContent = "Cookie: Đã nạp";
                badge.className = "text-emerald-400 font-semibold";

                title.textContent = "Đã có tệp cookies.txt đang hoạt động";
                const plats = data.platforms_detected.length > 0 ? data.platforms_detected.join(", ") : "Chung";
                details.textContent = `Dung lượng: ${formatBytes(data.size_bytes)} • Hỗ trợ: ${plats} • Cập nhật: ${data.last_modified || ''}`;
                btnDel.classList.remove("hidden");
            } else {
                badge.textContent = "Cài đặt Cookie";
                badge.className = "text-slate-200";

                title.textContent = "Chưa có file cookies.txt";
                details.textContent = "Các liên kết công khai vẫn tải bình thường. Nạp cookie nếu cần tải trang riêng tư/hạn chế.";
                btnDel.classList.add("hidden");
            }
        }
    } catch (e) {
        console.error("Lỗi kiểm tra cookie:", e);
    }
}

async function handleCookieUpload(e) {
    e.preventDefault();
    const fileInput = document.getElementById("cookieFileInput");
    if (!fileInput.files || fileInput.files.length === 0) {
        showToast("Vui lòng chọn một file cookies.txt", "error");
        return;
    }

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const btn = document.getElementById("btnUploadCookieSubmit");
    btn.disabled = true;
    btn.textContent = "Đang xử lý...";

    try {
        const res = await fetch("/api/settings/cookies", {
            method: "POST",
            body: formData
        });

        if (res.ok) {
            showToast("Đã nạp file cookies.txt thành công!", "success");
            fileInput.value = "";
            document.getElementById("cookieFileName").textContent = "";
            checkCookieStatus();
        } else {
            const err = await res.json();
            throw new Error(err.detail || "Tải lên thất bại");
        }
    } catch (e) {
        showToast(e.message, "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "Tải lên và Áp dụng";
    }
}

async function handleCookieDelete() {
    if (!confirm("Bạn có chắc chắn muốn xóa file cookies.txt đã lưu không?")) return;

    try {
        const res = await fetch("/api/settings/cookies", { method: "DELETE" });
        if (res.ok) {
            showToast("Đã xóa file cookies thành công", "success");
            checkCookieStatus();
        }
    } catch (e) {
        showToast("Lỗi khi xóa cookies", "error");
    }
}

// Custom Toast System
function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");

    let bg = "bg-slate-900 border-slate-700 text-white";
    let icon = "info";

    if (type === "success") {
        bg = "bg-emerald-950 border-emerald-700 text-emerald-200";
        icon = "check-circle";
    } else if (type === "error") {
        bg = "bg-rose-950 border-rose-800 text-rose-200";
        icon = "alert-triangle";
    }

    toast.className = `flex items-center space-x-2.5 px-4 py-3 rounded-xl border shadow-xl text-xs font-medium pointer-events-auto transition transform translate-y-2 opacity-0 ${bg}`;
    toast.innerHTML = `
        <i data-lucide="${icon}" class="w-4 h-4 shrink-0"></i>
        <span>${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);
    initLucide();

    // Animate in
    setTimeout(() => {
        toast.classList.remove("translate-y-2", "opacity-0");
    }, 10);

    // Auto remove after 4 seconds
    setTimeout(() => {
        toast.classList.add("opacity-0", "translate-y-2");
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// ---------------- Retry a failed / stuck vault ----------------
async function retryVault(vault) {
    const maxItems = parseInt(document.getElementById("maxItemsSelect")?.value || "50", 10);
    try {
        const res = await fetch(`/api/vaults/${vault.id}/retry?max_items=${maxItems}`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "Không thể tải lại");
        showToast("Đang tải lại...", "info");
        startBatchStream([data], [vault.custom_name], vault.custom_name);
        loadVaults();
    } catch (e) {
        showToast(e.message, "error");
    }
}

// ---------------- Link history ----------------
let historyCache = [];

async function loadHistory() {
    const panel = document.getElementById("historyPanel");
    panel.innerHTML = `<p class="px-3 py-3 text-xs text-slate-500">Đang tải...</p>`;
    try {
        const res = await fetch("/api/vaults/history");
        if (!res.ok) throw new Error();
        historyCache = await res.json();
    } catch (e) {
        panel.innerHTML = `<p class="px-3 py-3 text-xs text-rose-400">Không tải được lịch sử</p>`;
        return;
    }
    renderHistory();
}

function renderHistory() {
    const panel = document.getElementById("historyPanel");
    if (!historyCache.length) {
        panel.innerHTML = `<p class="px-3 py-3 text-xs text-slate-500">Chưa có link nào. Link bạn tải sẽ được lưu ở đây.</p>`;
        return;
    }
    panel.innerHTML = "";
    historyCache.forEach(h => {
        const pConf = PLATFORM_CONFIG[h.platform] || PLATFORM_CONFIG.other;
        const statusLabel = h.status === "completed" ? "" : (h.status === "error" ? "Lỗi" : "Chưa xong");
        const row = document.createElement("div");
        row.className = "flex items-center justify-between gap-2 px-3 py-2 hover:bg-slate-800/60";
        row.innerHTML = `
            <button type="button" class="hist-use min-w-0 flex-1 text-left" title="Điền link này vào ô nhập">
                <div class="flex items-center gap-2">
                    <span class="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase border ${pConf.color}">${pConf.name}</span>
                    <span class="text-xs font-semibold text-slate-200 truncate">${escapeHtml(h.custom_name)}</span>
                    ${statusLabel ? `<span class="text-[10px] text-rose-300">${statusLabel}</span>` : ""}
                </div>
                <div class="text-[11px] text-slate-500 truncate">${escapeHtml(h.url)}</div>
                <div class="text-[10px] text-slate-600">${formatDate(h.last_at)}${h.times > 1 ? ` • đã tải ${h.times} lần` : ""}</div>
            </button>
            <button type="button" class="hist-open shrink-0 text-[11px] px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300">Xem kho</button>`;
        row.querySelector(".hist-use").addEventListener("click", () => {
            const ta = document.getElementById("urlInput");
            const lines = parseUrlLines(ta.value);
            if (!lines.includes(h.url)) lines.push(h.url);
            ta.value = lines.join("\n");
            ta.dispatchEvent(new Event("input"));
            if (!document.getElementById("customNameInput").value) {
                document.getElementById("customNameInput").value = lines.length === 1 ? h.custom_name : "";
            }
            ta.focus();
        });
        row.querySelector(".hist-open").addEventListener("click", () => openGalleryModal(h.vault_id));
        panel.appendChild(row);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btnToggleHistory").addEventListener("click", () => {
        const panel = document.getElementById("historyPanel");
        const opening = panel.classList.contains("hidden");
        panel.classList.toggle("hidden");
        if (opening) loadHistory();
    });
});

// Warn when submitting a link that was already downloaded before
async function confirmDuplicates(urls) {
    try {
        const res = await fetch("/api/vaults/history");
        if (!res.ok) return true;
        const known = new Set((await res.json()).map(h => h.url.replace(/\/+$/, "")));
        const dups = urls.filter(u => known.has(u.replace(/\/+$/, "")));
        if (!dups.length) return true;
        return confirm(`${dups.length} link đã từng được tải trước đây:\n\n${dups.slice(0, 5).join("\n")}\n\nVẫn tải lại (sẽ tạo thêm kho mới)?`);
    } catch (e) {
        return true;
    }
}


// ---------------- Private content: paste page source ----------------
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btnSubmitSource").addEventListener("click", async () => {
        const html = document.getElementById("sourceInput").value;
        if (html.trim().length < 200) {
            showToast("Mã nguồn quá ngắn. Hãy sao chép TOÀN BỘ trang (Ctrl+A rồi Ctrl+C).", "error");
            return;
        }
        const btn = document.getElementById("btnSubmitSource");
        btn.disabled = true;
        const customName = document.getElementById("customNameInput").value.trim();
        try {
            const res = await fetch("/api/tasks/start-source", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    html: html,
                    custom_name: customName || null,
                    notes: document.getElementById("notesInput").value.trim() || null,
                    media_type: document.querySelector('input[name="mediaType"]:checked').value,
                    max_items: parseInt(document.getElementById("maxItemsSelect")?.value || "50", 10)
                })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join("; ") : data.detail;
                throw new Error(detail || "Không thể xử lý mã nguồn");
            }
            document.getElementById("sourceInput").value = "";
            document.getElementById("sourceBox").open = false;
            showToast("Đang tách video/ảnh từ mã nguồn...", "info");
            startBatchStream([data], [customName || "Mã nguồn trang"], customName || "Mã nguồn trang");
        } catch (e) {
            showToast(e.message, "error");
        } finally {
            btn.disabled = false;
        }
    });
});

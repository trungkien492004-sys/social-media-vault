// Social Media Vault Frontend Logic

let currentPlatformFilter = "all";
let currentSearchQuery = "";
let currentVaultDetail = null;
let currentMediaFilter = "all";
let activeEventSource = null;

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
    initLucide();
    loadStats();
    loadVaults();
    checkCookieStatus();
    setupEventListeners();
});

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
    other: {
        name: 'Media',
        color: 'bg-slate-700 text-slate-300 border-slate-600',
        icon: 'link'
    }
};

function detectPlatformFromUrl(url) {
    const lower = url.toLowerCase();
    if (lower.includes("tiktok.com")) return "tiktok";
    if (lower.includes("instagram.com")) return "instagram";
    if (lower.includes("threads.net")) return "threads";
    if (lower.includes("facebook.com") || lower.includes("fb.watch") || lower.includes("fb.com")) return "facebook";
    return "other";
}

// Setup Event Listeners
function setupEventListeners() {
    // 1. URL input typing auto-detection
    const urlInput = document.getElementById("urlInput");
    const detectedBadge = document.getElementById("detectedPlatformBadge");

    urlInput.addEventListener("input", (e) => {
        const val = e.target.value.trim();
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
                <h4 class="text-base font-bold text-white group-hover:text-indigo-400 transition truncate" title="${vault.custom_name}">
                    ${vault.custom_name}
                </h4>
                <p class="text-xs text-slate-400 mt-1 line-clamp-2 min-h-[2rem]">
                    ${vault.notes ? vault.notes : '<span class="italic text-slate-600">Không có ghi chú</span>'}
                </p>
            </div>

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
    card.querySelector(".btn-download-zip").addEventListener("click", () => triggerZipDownload(vault.id));
    card.querySelector(".btn-delete-vault").addEventListener("click", () => handleDeleteVault(vault.id, vault.custom_name));

    return card;
}

// Handle Form Submit & Start Extraction
async function handleExtractSubmit(e) {
    e.preventDefault();

    const url = document.getElementById("urlInput").value.trim();
    const customName = document.getElementById("customNameInput").value.trim();
    const notes = document.getElementById("notesInput").value.trim();
    const mediaType = document.querySelector('input[name="mediaType"]:checked').value;

    const btnSubmit = document.getElementById("btnSubmit");
    btnSubmit.disabled = true;

    try {
        const res = await fetch("/api/tasks/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: url,
                custom_name: customName,
                notes: notes,
                media_type: mediaType
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Không thể khởi tạo tác vụ");
        }

        const taskData = await res.json();
        showToast("Bắt đầu trích xuất media...", "info");

        // Clear input form
        document.getElementById("urlInput").value = "";
        document.getElementById("customNameInput").value = "";
        document.getElementById("notesInput").value = "";
        document.getElementById("detectedPlatformBadge").classList.add("hidden");

        // Start SSE listener
        startTaskStream(taskData.task_id, customName);

    } catch (err) {
        showToast(err.message, "error");
    } finally {
        btnSubmit.disabled = false;
    }
}

// SSE Task Stream Listener
function startTaskStream(taskId, customName) {
    if (activeEventSource) {
        activeEventSource.close();
    }

    const progressSection = document.getElementById("progressSection");
    const progressTitle = document.getElementById("progressTitle");
    const progressMessage = document.getElementById("progressMessage");
    const progressBar = document.getElementById("progressBar");
    const progressPercentBadge = document.getElementById("progressPercentBadge");
    const progressCountBadge = document.getElementById("progressCountBadge");
    const progressSpinner = document.getElementById("progressSpinner");
    const liveFeedContainer = document.getElementById("liveFeedContainer");
    const liveFeedList = document.getElementById("liveFeedList");

    progressSection.classList.remove("hidden");
    liveFeedContainer.classList.add("hidden");
    liveFeedList.innerHTML = "";

    progressTitle.textContent = `Đang xử lý: ${customName}`;
    progressMessage.textContent = "Đang kết nối đến máy chủ...";
    progressBar.style.width = "5%";
    progressPercentBadge.textContent = "5%";
    progressCountBadge.textContent = "0/0";
    progressSpinner.classList.add("animate-spin");

    activeEventSource = new EventSource(`/api/tasks/${taskId}/stream`);

    activeEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.message) {
                progressMessage.textContent = data.message;
            }

            if (data.progress !== undefined) {
                const percent = Math.min(100, Math.max(0, data.progress));
                progressBar.style.width = `${percent}%`;
                progressPercentBadge.textContent = `${percent}%`;
            }

            if (data.total > 0) {
                progressCountBadge.textContent = `${data.current || 0}/${data.total}`;
            }

            // Handle latest downloaded thumbnail preview
            if (data.latest_item) {
                liveFeedContainer.classList.remove("hidden");
                const item = data.latest_item;
                const mini = document.createElement("div");
                mini.className = "w-14 h-14 rounded-lg bg-slate-800 overflow-hidden shrink-0 border border-slate-700 relative flex items-center justify-center";

                if (item.file_type === "image") {
                    mini.innerHTML = `<img src="/vault/${item.file_path}" class="w-full h-full object-cover" />`;
                } else {
                    mini.innerHTML = `
                        <video src="/vault/${item.file_path}" class="w-full h-full object-cover"></video>
                        <div class="absolute inset-0 bg-black/40 flex items-center justify-center">
                            <i data-lucide="play" class="w-4 h-4 text-white"></i>
                        </div>
                    `;
                }
                liveFeedList.prepend(mini);
                initLucide();
            }

            // Handle Task Completion
            if (data.status === "completed") {
                progressSpinner.classList.remove("animate-spin");
                progressSpinner.innerHTML = `<i data-lucide="check-circle" class="w-5 h-5 text-emerald-400"></i>`;
                progressBar.classList.remove("from-indigo-500");
                progressBar.classList.add("from-emerald-500", "to-teal-400");
                showToast("Đã trích xuất & lưu trữ thành công!", "success");

                loadStats();
                loadVaults();
                initLucide();
                activeEventSource.close();
            }

            // Handle Task Error
            if (data.status === "error") {
                progressSpinner.classList.remove("animate-spin");
                progressSpinner.innerHTML = `<i data-lucide="alert-circle" class="w-5 h-5 text-rose-400"></i>`;
                progressBar.classList.add("bg-rose-600");
                showToast(data.message || "Đã xảy ra lỗi khi cào media", "error");
                initLucide();
                activeEventSource.close();
            }
        } catch (e) {
            console.error("Lỗi phân tích SSE:", e);
        }
    };

    activeEventSource.onerror = (err) => {
        console.warn("SSE connection error or closed");
        activeEventSource.close();
    };
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

        const filePath = `/vault/${item.file_path}`;

        if (item.file_type === "image") {
            itemEl.innerHTML = `
                <img src="${filePath}" loading="lazy" class="w-full h-full object-cover group-hover:scale-105 transition duration-300" />
                <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent opacity-0 group-hover:opacity-100 transition p-2.5 flex flex-col justify-between">
                    <span class="self-end text-[10px] bg-indigo-600/90 text-white font-semibold px-2 py-0.5 rounded">Ảnh</span>
                    <p class="text-[11px] text-white truncate">${item.caption || item.file_name}</p>
                </div>
            `;
        } else {
            itemEl.innerHTML = `
                <video src="${filePath}" preload="metadata" class="w-full h-full object-cover"></video>
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

        itemEl.addEventListener("click", () => openLightbox(item));
        grid.appendChild(itemEl);
    });

    initLucide();
}

// Lightbox Preview (HD Photo or Video Player)
function openLightbox(item) {
    const modal = document.getElementById("lightboxModal");
    const container = document.getElementById("lightboxContent");
    const captionEl = document.getElementById("lightboxCaption");
    const btnDownload = document.getElementById("lightboxBtnDownload");

    const filePath = `/vault/${item.file_path}`;

    captionEl.textContent = item.caption || item.file_name;
    btnDownload.href = filePath;
    btnDownload.setAttribute("download", item.file_name);

    if (item.file_type === "image") {
        container.innerHTML = `<img src="${filePath}" class="max-h-[75vh] w-auto max-w-full rounded-lg object-contain shadow-2xl" />`;
    } else {
        container.innerHTML = `
            <video src="${filePath}" controls autoplay class="max-h-[75vh] w-auto max-w-full rounded-lg shadow-2xl">
                Trình duyệt của bạn không hỗ trợ thẻ video.
            </video>
        `;
    }

    modal.classList.remove("hidden");
    initLucide();
}

function closeLightbox() {
    const modal = document.getElementById("lightboxModal");
    const container = document.getElementById("lightboxContent");
    // Stop video playing if open
    const video = container.querySelector("video");
    if (video) video.pause();
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
        <span>${message}</span>
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

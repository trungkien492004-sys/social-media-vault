/* Chọn nhiều / Xóa / Chỉnh sửa ảnh & video (loaded after app.js, shares its globals) */
let selectMode = false;
const selectedIds = new Set();

function updateSelectUi() {
    const btnMode = document.getElementById("btnSelectMode");
    if (!btnMode) return;
    btnMode.textContent = selectMode ? "Xong" : "Chọn nhiều";
    document.getElementById("btnSelectAll").classList.toggle("hidden", !selectMode);
    const del = document.getElementById("btnDeleteSelected");
    del.classList.toggle("hidden", !selectMode);
    del.textContent = `Xóa (${selectedIds.size})`;
}

function refreshVaultCounts() {
    const d = currentVaultDetail;
    if (!d) return;
    const items = d.media_items || [];
    d.total_items = items.length;
    d.total_images = items.filter(i => i.file_type === "image").length;
    d.total_videos = items.filter(i => i.file_type === "video").length;
    d.total_size_bytes = items.reduce((s, i) => s + (i.file_size || 0), 0);
    document.getElementById("modalCountAll").textContent = d.total_items;
    document.getElementById("modalCountImg").textContent = d.total_images;
    document.getElementById("modalCountVid").textContent = d.total_videos;
    document.getElementById("modalTotalSize").textContent = formatBytes(d.total_size_bytes);
}

async function deleteMediaIds(ids) {
    const d = currentVaultDetail;
    if (!d || !ids.length) return false;
    try {
        const res = await fetch(`/api/vaults/${d.id}/media/delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ids }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "Không thể xóa tệp");
        const gone = new Set(ids);
        d.media_items = (d.media_items || []).filter(i => !gone.has(i.id));
        refreshVaultCounts();
        loadStats();
        loadVaults();
        return true;
    } catch (e) {
        showToast(e.message, "error");
        return false;
    }
}

async function deleteCurrentLightboxItem() {
    const item = lightboxItems[lightboxIndex];
    if (!item) return;
    if (!confirm(`Xóa vĩnh viễn "${item.file_name}" khỏi kho?`)) return;
    if (!(await deleteMediaIds([item.id]))) return;
    lightboxItems = lightboxItems.filter(i => i.id !== item.id);
    showToast("Đã xóa khỏi kho", "success");
    if (!lightboxItems.length) {
        closeLightbox();
    } else {
        lightboxIndex = Math.min(lightboxIndex, lightboxItems.length - 1);
        renderLightbox();
    }
    renderModalMedia();
}

/* ---------- Editor ---------- */
const ed = { item: null, kind: null, img: null, mime: "image/jpeg", quarter: 0, flipH: false, flipV: false, crop: null, blobUrl: null, duration: 0 };
const edEl = (id) => document.getElementById(id);

function edFilterCss() {
    return `brightness(${edEl("editBrightness").value}%) contrast(${edEl("editContrast").value}%) saturate(${edEl("editSaturation").value}%)`;
}

function edUpdatePreview() {
    edEl("valBrightness").textContent = edEl("editBrightness").value + "%";
    edEl("valContrast").textContent = edEl("editContrast").value + "%";
    edEl("valSaturation").textContent = edEl("editSaturation").value + "%";
    const f = edFilterCss();
    if (ed.kind === "image") {
        edEl("editorCanvas").style.filter = f;
    } else {
        const v = edEl("editorVideo");
        const odd = ed.quarter % 2 === 1;
        v.style.filter = f;
        v.style.transform = `scale(${ed.flipH ? -1 : 1}, ${ed.flipV ? -1 : 1}) rotate(${ed.quarter * 90}deg)${odd ? " scale(0.6)" : ""}`;
        edEl("editorVideoWrap").style.minHeight = odd ? "60vh" : "";
    }
}

function edDrawImage() {
    const img = ed.img;
    if (!img) return;
    const odd = ed.quarter % 2 === 1;
    const cv = edEl("editorCanvas");
    cv.width = odd ? img.naturalHeight : img.naturalWidth;
    cv.height = odd ? img.naturalWidth : img.naturalHeight;
    const ctx = cv.getContext("2d");
    ctx.save();
    ctx.translate(cv.width / 2, cv.height / 2);
    ctx.scale(ed.flipH ? -1 : 1, ed.flipV ? -1 : 1);
    ctx.rotate(ed.quarter * Math.PI / 2);
    ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
    ctx.restore();
    ed.crop = null;
    edShowCrop();
}

function edShowCrop() {
    const box = edEl("cropBox");
    if (!ed.crop) { box.classList.add("hidden"); return; }
    const cv = edEl("editorCanvas");
    const sx = cv.clientWidth / cv.width, sy = cv.clientHeight / cv.height;
    box.style.left = ed.crop.x * sx + "px";
    box.style.top = ed.crop.y * sy + "px";
    box.style.width = ed.crop.w * sx + "px";
    box.style.height = ed.crop.h * sy + "px";
    box.classList.remove("hidden");
}

function edTransformAction(act) {
    if (act === "rotR" || act === "rotL") {
        let delta = act === "rotR" ? 1 : -1;
        if (ed.flipH !== ed.flipV) delta = -delta; // a mirrored image turns the other way
        ed.quarter = (ed.quarter + delta + 4) % 4;
    } else if (act === "flipH") {
        ed.flipH = !ed.flipH;
    } else if (act === "flipV") {
        ed.flipV = !ed.flipV;
    }
    if (ed.kind === "image") edDrawImage();
    edUpdatePreview();
}

function edReset() {
    ed.quarter = 0; ed.flipH = false; ed.flipV = false; ed.crop = null;
    edEl("editBrightness").value = 100;
    edEl("editContrast").value = 100;
    edEl("editSaturation").value = 100;
    if (ed.kind === "image") {
        edDrawImage();
    } else {
        edEl("trimStart").value = 0;
        edEl("trimEnd").value = ed.duration ? ed.duration.toFixed(1) : 0;
    }
    edUpdatePreview();
}

async function openEditor(item) {
    const d = currentVaultDetail;
    if (!d) return;
    ed.item = item;
    ed.kind = item.file_type === "video" ? "video" : "image";
    ed.quarter = 0; ed.flipH = false; ed.flipV = false; ed.crop = null; ed.duration = 0; ed.img = null;
    edEl("editBrightness").value = 100;
    edEl("editContrast").value = 100;
    edEl("editSaturation").value = 100;
    edEl("editorStatus").textContent = "";
    edEl("editorBtnSave").disabled = false;
    edEl("editorTitle").textContent = `${ed.kind === "image" ? "Chỉnh sửa ảnh" : "Chỉnh sửa video"} — ${item.file_name}`;
    edEl("editorImageWrap").classList.toggle("hidden", ed.kind !== "image");
    edEl("editorVideoWrap").classList.toggle("hidden", ed.kind !== "video");
    edEl("editorCropControls").classList.toggle("hidden", ed.kind !== "image");
    edEl("editorTrimControls").classList.toggle("hidden", ed.kind !== "video");
    edEl("editorModal").classList.remove("hidden");

    // stop the lightbox video so two players don't run at once
    const lbVideo = edEl("lightboxContent").querySelector("video");
    if (lbVideo) lbVideo.pause();

    if (ed.kind === "image") {
        edEl("editorStatus").textContent = "Đang tải ảnh...";
        try {
            const res = await fetch(`/api/vaults/${d.id}/media/${item.id}/raw`);
            if (!res.ok) throw new Error("Không tải được ảnh gốc");
            const blob = await res.blob();
            ed.mime = /png/.test(blob.type) ? "image/png" : /webp/.test(blob.type) ? "image/webp" : "image/jpeg";
            if (ed.blobUrl) URL.revokeObjectURL(ed.blobUrl);
            ed.blobUrl = URL.createObjectURL(blob);
            const img = new Image();
            await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error("Ảnh không hợp lệ")); img.src = ed.blobUrl; });
            ed.img = img;
            edDrawImage();
            edEl("editorStatus").textContent = "";
        } catch (e) {
            edEl("editorStatus").textContent = e.message;
            showToast(e.message, "error");
        }
    } else {
        const v = edEl("editorVideo");
        v.onloadedmetadata = () => {
            ed.duration = v.duration || 0;
            edEl("trimStart").value = 0;
            edEl("trimEnd").value = ed.duration.toFixed(1);
        };
        v.src = mediaUrl(item);
    }
    edUpdatePreview();
    initLucide();
}

function closeEditor() {
    const v = edEl("editorVideo");
    v.pause(); v.removeAttribute("src"); v.load();
    v.style.transform = ""; v.style.filter = "";
    edEl("editorModal").classList.add("hidden");
    ed.img = null;
}

function edPixelFilter(ctx, w, h) {
    const b = edEl("editBrightness").value / 100, c = edEl("editContrast").value / 100, s = edEl("editSaturation").value / 100;
    const data = ctx.getImageData(0, 0, w, h), px = data.data;
    for (let i = 0; i < px.length; i += 4) {
        let r = px[i] * b, g = px[i + 1] * b, bl = px[i + 2] * b;
        r = (r - 128) * c + 128; g = (g - 128) * c + 128; bl = (bl - 128) * c + 128;
        const gray = 0.299 * r + 0.587 * g + 0.114 * bl;
        px[i] = Math.max(0, Math.min(255, gray + (r - gray) * s));
        px[i + 1] = Math.max(0, Math.min(255, gray + (g - gray) * s));
        px[i + 2] = Math.max(0, Math.min(255, gray + (bl - gray) * s));
    }
    ctx.putImageData(data, 0, 0);
}

async function saveEditor() {
    const d = currentVaultDetail, item = ed.item;
    if (!d || !item) return;
    const mode = edEl("editorMode").value;
    const btn = edEl("editorBtnSave");
    const status = edEl("editorStatus");
    btn.disabled = true;
    try {
        let res;
        if (ed.kind === "image") {
            if (!ed.img) throw new Error("Ảnh chưa tải xong");
            status.textContent = "Đang xử lý ảnh...";
            const src = edEl("editorCanvas");
            const rect = ed.crop && ed.crop.w > 4 && ed.crop.h > 4 ? ed.crop : { x: 0, y: 0, w: src.width, h: src.height };
            const out = document.createElement("canvas");
            out.width = Math.max(1, Math.round(rect.w));
            out.height = Math.max(1, Math.round(rect.h));
            const ctx = out.getContext("2d");
            const filtered = !(edEl("editBrightness").value == 100 && edEl("editContrast").value == 100 && edEl("editSaturation").value == 100);
            const native = "filter" in ctx;
            if (filtered && native) ctx.filter = edFilterCss();
            ctx.drawImage(src, Math.round(rect.x), Math.round(rect.y), out.width, out.height, 0, 0, out.width, out.height);
            if (filtered && !native) edPixelFilter(ctx, out.width, out.height);
            const blob = await new Promise(r => out.toBlob(r, ed.mime, 0.92));
            if (!blob) throw new Error("Trình duyệt không xuất được ảnh");
            const fd = new FormData();
            fd.append("file", blob, "edited");
            fd.append("mode", mode);
            status.textContent = "Đang lưu...";
            res = await fetch(`/api/vaults/${d.id}/media/${item.id}/edit-image`, { method: "POST", body: fd });
        } else {
            const start = parseFloat(edEl("trimStart").value) || 0;
            let end = parseFloat(edEl("trimEnd").value) || 0;
            if (!end || (ed.duration && end >= ed.duration - 0.05)) end = null;
            if (end !== null && end <= start) throw new Error("Điểm cuối phải lớn hơn điểm đầu");
            status.textContent = "Đang xử lý video trên máy chủ, có thể mất vài phút...";
            res = await fetch(`/api/vaults/${d.id}/media/${item.id}/edit-video`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    start, end,
                    rotate: ed.quarter * 90,
                    flip_h: ed.flipH, flip_v: ed.flipV,
                    brightness: edEl("editBrightness").value / 100,
                    contrast: edEl("editContrast").value / 100,
                    saturation: edEl("editSaturation").value / 100,
                    mode,
                }),
            });
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Không thể lưu chỉnh sửa");
        showToast(mode === "copy" ? "Đã lưu thành tệp mới" : "Đã lưu chỉnh sửa", "success");
        const vaultId = d.id;
        closeEditor();
        closeLightbox();
        await openGalleryModal(vaultId);
        loadStats();
        loadVaults();
    } catch (e) {
        status.textContent = e.message;
        showToast(e.message, "error");
    } finally {
        btn.disabled = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    edEl("lightboxBtnEdit").addEventListener("click", () => { const it = lightboxItems[lightboxIndex]; if (it) openEditor(it); });
    edEl("lightboxBtnDelete").addEventListener("click", deleteCurrentLightboxItem);
    edEl("editorBtnClose").addEventListener("click", closeEditor);
    edEl("editorBtnSave").addEventListener("click", saveEditor);
    edEl("editorBtnReset").addEventListener("click", edReset);
    edEl("editorBtnClearCrop").addEventListener("click", () => { ed.crop = null; edShowCrop(); });
    document.querySelectorAll("[data-edit-act]").forEach(b => b.addEventListener("click", () => edTransformAction(b.dataset.editAct)));
    ["editBrightness", "editContrast", "editSaturation"].forEach(id => edEl(id).addEventListener("input", edUpdatePreview));
    edEl("trimSetStart").addEventListener("click", () => { edEl("trimStart").value = edEl("editorVideo").currentTime.toFixed(1); });
    edEl("trimSetEnd").addEventListener("click", () => { edEl("trimEnd").value = edEl("editorVideo").currentTime.toFixed(1); });

    // Crop by dragging on the canvas
    const cv = edEl("editorCanvas");
    let drag = null;
    const pt = (e) => {
        const r = cv.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(cv.width, (e.clientX - r.left) * cv.width / r.width)),
            y: Math.max(0, Math.min(cv.height, (e.clientY - r.top) * cv.height / r.height)),
        };
    };
    cv.addEventListener("pointerdown", (e) => { drag = pt(e); cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", (e) => {
        if (!drag) return;
        const p = pt(e);
        ed.crop = { x: Math.min(drag.x, p.x), y: Math.min(drag.y, p.y), w: Math.abs(p.x - drag.x), h: Math.abs(p.y - drag.y) };
        edShowCrop();
    });
    const endDrag = () => { drag = null; if (ed.crop && (ed.crop.w < 8 || ed.crop.h < 8)) { ed.crop = null; edShowCrop(); } };
    cv.addEventListener("pointerup", endDrag);
    cv.addEventListener("pointercancel", endDrag);

    // Multi-select delete
    edEl("btnSelectMode").addEventListener("click", () => {
        selectMode = !selectMode;
        selectedIds.clear();
        updateSelectUi();
        renderModalMedia();
    });
    edEl("btnSelectAll").addEventListener("click", () => {
        const items = (currentVaultDetail?.media_items || []).filter(i => currentMediaFilter === "all" || i.file_type === currentMediaFilter);
        const allOn = items.every(i => selectedIds.has(i.id));
        items.forEach(i => allOn ? selectedIds.delete(i.id) : selectedIds.add(i.id));
        updateSelectUi();
        renderModalMedia();
    });
    edEl("btnDeleteSelected").addEventListener("click", async () => {
        const ids = [...selectedIds];
        if (!ids.length) return showToast("Chưa chọn tệp nào", "info");
        if (!confirm(`Xóa vĩnh viễn ${ids.length} tệp đã chọn khỏi kho?`)) return;
        if (await deleteMediaIds(ids)) {
            selectedIds.clear();
            showToast(`Đã xóa ${ids.length} tệp`, "success");
            updateSelectUi();
            renderModalMedia();
        }
    });
});

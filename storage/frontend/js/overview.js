import { CONFIG } from "./config.js";
import { api, fetchImageUrl, invalidateImageUrl } from "./api.js";
import { icons } from "./icons.js";
import { getCurrentUserInfo } from "./auth.js";
import { showToast } from "./toast.js";
import { showConfirmDialog } from "./confirmDialog.js";

const PAGE_SIZE = 20;

// Persists across re-renders within the same page load (e.g. navigating
// to Settings and back keeps your filters), resets on a full reload.
const state = {
  q: "",
  room: "",
  level: "",
  shelf: "",
  minQuantity: "",
  maxQuantity: "",
  sortBy: "name",
  sortDir: "asc",
  offset: 0,
  total: 0,
};

let locationsCache = null;
let roomsCache = null;
let debounceTimer = null;
let currentItems = [];

function canWrite() {
  const info = getCurrentUserInfo();
  return info && (info.role === "admin" || info.role === "user");
}

function debounce(fn, delay) {
  return (...args) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fn(...args), delay);
  };
}

function buildQuery() {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.room) params.set("room", state.room);
  if (state.level) params.set("level", state.level);
  if (state.shelf) params.set("shelf", state.shelf);
  if (state.minQuantity !== "") params.set("min_quantity", state.minQuantity);
  if (state.maxQuantity !== "") params.set("max_quantity", state.maxQuantity);
  params.set("sort_by", state.sortBy);
  params.set("sort_dir", state.sortDir);
  params.set("limit", PAGE_SIZE);
  params.set("offset", state.offset);
  return params.toString();
}

function quantityLabel(item) {
  if (item.quantity_type === "countable") {
    return `${item.quantity ?? 0}×`;
  }
  return item.quantity_note || "uncountable";
}

function locationLabel(item) {
  if (!item.location) return null;
  return [item.location.room, item.location.level, item.location.shelf].filter(Boolean).join(" · ");
}

export async function renderOverview(container) {
  container.innerHTML = `
    <div class="page">
      <div class="stack" style="margin-bottom: var(--space-3);">
        <div class="search-bar">
          ${icons.search}
          <input type="search" id="search-input" placeholder="Search items…" value="${escapeAttr(state.q)}" />
        </div>
        <div class="row">
          <button class="btn grow" id="filter-toggle">${icons.filter}<span>Filter</span></button>
          <select class="select" id="sort-select" style="flex: 1;">
            <option value="name-asc">Name (A–Z)</option>
            <option value="name-desc">Name (Z–A)</option>
            <option value="quantity-asc">Quantity (low–high)</option>
            <option value="quantity-desc">Quantity (high–low)</option>
            <option value="updated_at-desc">Recently updated</option>
            <option value="created_at-desc">Newest first</option>
          </select>
          <button class="btn btn-icon" id="select-toggle" aria-label="Select items" title="Select items">${icons.checklist}</button>
        </div>
        <div class="filter-panel hidden" id="filter-panel">
          <div class="field-row">
            <div class="field">
              <label for="filter-room">Room</label>
              <select class="select" id="filter-room"><option value="">Any</option></select>
            </div>
            <div class="field">
              <label>Quantity</label>
              <div class="row">
                <input class="input" type="number" min="0" id="filter-min-qty" placeholder="Min" value="${escapeAttr(state.minQuantity)}" />
                <input class="input" type="number" min="0" id="filter-max-qty" placeholder="Max" value="${escapeAttr(state.maxQuantity)}" />
              </div>
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>Shelf</label>
              <button type="button" class="btn btn-block" id="filter-shelf-btn" style="justify-content: space-between;">
                <span id="filter-shelf-label">Any</span>
                ${icons.chevronRight}
              </button>
            </div>
            <div class="field">
              <label for="filter-level">Shelf level</label>
              <input class="input" type="number" id="filter-level" placeholder="Any" value="${escapeAttr(state.level)}" />
            </div>
          </div>
          <button class="btn" id="filter-clear">Clear filters</button>
        </div>
      </div>

      <div id="item-grid" class="item-grid" aria-live="polite"></div>
      <div id="pagination-root"></div>
    </div>
    <div id="bulk-bar-root"></div>
    <button class="fab" id="add-item-fab" aria-label="Add item">${icons.plus}</button>
  `;

  const searchInput = container.querySelector("#search-input");
  searchInput.addEventListener(
    "input",
    debounce((e) => {
      state.q = e.target.value;
      state.offset = 0;
      refreshItems(container, selection);
    }, 300)
  );

  const filterToggle = container.querySelector("#filter-toggle");
  const filterPanel = container.querySelector("#filter-panel");
  filterToggle.addEventListener("click", () => filterPanel.classList.toggle("hidden"));

  const sortSelect = container.querySelector("#sort-select");
  sortSelect.value = `${state.sortBy}-${state.sortDir}`;
  sortSelect.addEventListener("change", (e) => {
    const [by, dir] = e.target.value.split("-");
    state.sortBy = by;
    state.sortDir = dir;
    state.offset = 0;
    refreshItems(container, selection);
  });

  const roomSelect = container.querySelector("#filter-room");
  const levelInput = container.querySelector("#filter-level");
  const shelfBtn = container.querySelector("#filter-shelf-btn");
  const shelfLabel = container.querySelector("#filter-shelf-label");
  // Shelf isn't a managed list like Room — it's whatever free text has
  // been typed into items' locations so far, which can grow into a long,
  // unsearchable list on mobile as a real inventory fills in. A popup
  // picker (openShelfPickerModal) with search stays usable at any size;
  // Room stays a native <select> since the managed-rooms list it's
  // populated from is small and curated by design.
  let currentShelves = [];

  async function loadLocations() {
    if (!locationsCache) {
      try {
        locationsCache = await api.get(`${CONFIG.STORAGE_BASE}/locations`);
      } catch {
        locationsCache = [];
      }
    }
    // Always fresh (not cached-once like locations above) — rooms can be
    // added/removed on the Rooms management page, and this page shouldn't
    // keep showing a stale list after a visit there.
    try {
      roomsCache = await api.get(`${CONFIG.STORAGE_BASE}/rooms`);
    } catch {
      roomsCache = roomsCache || [];
    }
    populateLocationFilters();
  }

  function populateLocationFilters() {
    // Room comes from the managed list (Settings → Manage rooms), not
    // from whatever rooms items happen to already use — so a freshly
    // added, not-yet-used room still shows up as a filter option.
    const rooms = roomsCache.map((r) => r.name).sort();
    const relevant = locationsCache.filter((l) => !state.room || l.room === state.room);
    currentShelves = [...new Set(relevant.map((l) => l.shelf).filter(Boolean))].sort();

    fillSelect(roomSelect, rooms, state.room);
    shelfLabel.textContent = state.shelf || "Any";
  }

  function fillSelect(selectEl, values, selected) {
    const current = selectEl.querySelector('option[value=""]').outerHTML;
    selectEl.innerHTML = current + values.map((v) => `<option value="${escapeAttr(v)}">${escapeHtml(v)}</option>`).join("");
    selectEl.value = selected;
  }

  roomSelect.addEventListener("change", (e) => {
    state.room = e.target.value;
    state.level = "";
    state.shelf = "";
    levelInput.value = "";
    state.offset = 0;
    populateLocationFilters();
    refreshItems(container, selection);
  });
  levelInput.addEventListener(
    "input",
    debounce((e) => {
      state.level = e.target.value;
      state.offset = 0;
      refreshItems(container, selection);
    }, 300)
  );
  shelfBtn.addEventListener("click", () => {
    openShelfPickerModal({
      shelves: currentShelves,
      selected: state.shelf,
      onSelect: (shelf) => {
        state.shelf = shelf;
        shelfLabel.textContent = shelf || "Any";
        state.offset = 0;
        refreshItems(container, selection);
      },
    });
  });

  const minQtyInput = container.querySelector("#filter-min-qty");
  const maxQtyInput = container.querySelector("#filter-max-qty");
  minQtyInput.addEventListener(
    "input",
    debounce((e) => {
      state.minQuantity = e.target.value;
      state.offset = 0;
      refreshItems(container, selection);
    }, 300)
  );
  maxQtyInput.addEventListener(
    "input",
    debounce((e) => {
      state.maxQuantity = e.target.value;
      state.offset = 0;
      refreshItems(container, selection);
    }, 300)
  );

  container.querySelector("#filter-clear").addEventListener("click", () => {
    state.room = "";
    state.level = "";
    state.shelf = "";
    state.minQuantity = "";
    state.maxQuantity = "";
    minQtyInput.value = "";
    maxQtyInput.value = "";
    levelInput.value = "";
    state.offset = 0;
    populateLocationFilters();
    refreshItems(container, selection);
  });

  const fab = container.querySelector("#add-item-fab");
  const selectToggle = container.querySelector("#select-toggle");

  // Selection state lives for the lifetime of this render only — it
  // intentionally resets if you navigate away and back to Overview.
  const selection = { mode: false, ids: new Set() };

  if (canWrite()) {
    fab.addEventListener("click", () => openAddModal(container));
    selectToggle.addEventListener("click", () => {
      selection.mode = !selection.mode;
      selection.ids.clear();
      selectToggle.classList.toggle("btn-primary", selection.mode);
      fab.classList.toggle("hidden", selection.mode);
      renderGrid(container, selection);
    });
  } else {
    fab.classList.add("hidden"); // viewers can't create items
    selectToggle.classList.add("hidden"); // ...or bulk edit/delete them
  }

  await loadLocations();
  await refreshItems(container, selection);
}

async function refreshItems(container, selection) {
  const grid = container.querySelector("#item-grid");
  if (!grid) return; // navigated away before this resolved

  const skeletonHtml = Array.from({ length: 6 })
    .map(() => `<div class="skeleton" style="aspect-ratio: 3/4;"></div>`)
    .join("");
  const cancelSkeleton = showSkeletonAfterDelay(grid, skeletonHtml);

  let page;
  try {
    page = await api.get(`${CONFIG.STORAGE_BASE}/items?${buildQuery()}`);
  } catch {
    cancelSkeleton();
    grid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;">Couldn't load items. Pull down to retry.</div>`;
    return;
  }
  cancelSkeleton();

  state.total = page.total;
  currentItems = page.items;
  renderGrid(container, selection);
}

// Rebuilds the grid/pagination/bulk-bar from the already-fetched
// currentItems cache, with no network call and no skeleton flash. Used
// whenever only the selection UI changes (entering/exiting/cancelling
// bulk-select) — the set of items on screen hasn't changed, just how
// each card is drawn.
function renderGrid(container, selection) {
  const grid = container.querySelector("#item-grid");
  const paginationRoot = container.querySelector("#pagination-root");
  if (!grid) return;

  if (currentItems.length === 0) {
    grid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;">${icons.box}<p style="margin-top: var(--space-2);">No items found</p></div>`;
  } else {
    grid.innerHTML = "";
    currentItems.forEach((item) => grid.appendChild(renderItemCard(item, container, selection)));
  }

  renderPagination(paginationRoot, container, selection);
  renderBulkBar(container, selection);
}

function renderItemCard(item, container, selection) {
  const card = document.createElement("button");
  card.className = "item-card";
  card.type = "button";

  const inSelectionMode = selection && selection.mode;
  const isSelected = inSelectionMode && selection.ids.has(item.id);
  card.classList.toggle("selected", Boolean(isSelected));

  const thumb = document.createElement("div");
  thumb.className = "item-thumb";
  thumb.style.position = "relative";
  if (item.image_path) {
    thumb.innerHTML = icons.image; // placeholder while the authenticated fetch resolves
    fetchImageUrl(`${CONFIG.STORAGE_BASE}/items/${item.id}/image`).then((objectUrl) => {
      if (!objectUrl) return; // fetch failed — keep the placeholder icon
      const img = document.createElement("img");
      img.src = objectUrl;
      img.alt = item.name;
      thumb.innerHTML = ""; // clears the placeholder — badge must go AFTER this
      thumb.appendChild(img);
      if (inSelectionMode) thumb.appendChild(selectionBadge(isSelected));
    });
  } else {
    thumb.innerHTML = icons.image;
    if (inSelectionMode) thumb.appendChild(selectionBadge(isSelected));
  }

  const body = document.createElement("div");
  body.className = "item-card-body";

  const name = document.createElement("div");
  name.className = "item-name";
  name.textContent = item.name;

  const meta = document.createElement("div");
  meta.className = "item-meta";
  const qtySpan = document.createElement("span");
  qtySpan.textContent = quantityLabel(item);
  const locSpan = document.createElement("span");
  locSpan.textContent = locationLabel(item) || "";
  meta.append(qtySpan, locSpan);

  body.append(name, meta);
  card.append(thumb, body);

  card.addEventListener("click", () => {
    if (inSelectionMode) {
      toggleCardSelection(container, selection, item.id, card);
    } else {
      openItemModal(item, container);
    }
  });
  return card;
}

// Selecting a card used to call refreshItems() — a full re-fetch plus a
// from-scratch rebuild of every card (skeleton flash, thumbnails resetting
// to the placeholder icon and reloading) on every single tap. Toggling
// selection doesn't change what items exist, so it only needs to update
// the tapped card's own classes/badge and the bulk bar's count.
function toggleCardSelection(container, selection, itemId, card) {
  const nowSelected = !selection.ids.has(itemId);
  if (nowSelected) {
    selection.ids.add(itemId);
  } else {
    selection.ids.delete(itemId);
  }

  card.classList.toggle("selected", nowSelected);
  const badge = card.querySelector(".selection-badge");
  if (badge) {
    badge.classList.toggle("selection-badge-checked", nowSelected);
    badge.innerHTML = nowSelected ? icons.check : "";
  }
  renderBulkBar(container, selection);
}

function selectionBadge(isSelected) {
  const badge = document.createElement("div");
  badge.className = "selection-badge" + (isSelected ? " selection-badge-checked" : "");
  if (isSelected) badge.innerHTML = icons.check;
  return badge;
}

function renderBulkBar(container, selection) {
  const root = container.querySelector("#bulk-bar-root");
  if (!root) return;

  if (!selection || !selection.mode) {
    root.innerHTML = "";
    return;
  }

  const count = selection.ids.size;
  root.innerHTML = `
    <div class="bulk-bar">
      <span class="bulk-bar-count">${count} selected</span>
      <button class="btn btn-icon" id="bulk-cancel" aria-label="Cancel selection">${icons.close}</button>
      <button class="btn grow" id="bulk-edit-btn" ${count === 0 ? "disabled" : ""}>Edit</button>
      <button class="btn btn-danger grow" id="bulk-delete-btn" ${count === 0 ? "disabled" : ""}>${icons.trash}<span>Delete</span></button>
    </div>
  `;

  root.querySelector("#bulk-cancel").addEventListener("click", () => {
    selection.mode = false;
    selection.ids.clear();
    container.querySelector("#select-toggle").classList.remove("btn-primary");
    container.querySelector("#add-item-fab").classList.remove("hidden");
    renderGrid(container, selection);
  });

  root.querySelector("#bulk-edit-btn").addEventListener("click", () => {
    openBulkEditModal(container, selection);
  });

  root.querySelector("#bulk-delete-btn").addEventListener("click", async () => {
    const ok = await showConfirmDialog({
      title: "Delete items",
      message: `Delete ${count} item${count === 1 ? "" : "s"}? This can't be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      const result = await api.post(`${CONFIG.STORAGE_BASE}/items/bulk-delete`, {
        item_ids: [...selection.ids],
      });
      showToast(`Deleted ${result.deleted} item${result.deleted === 1 ? "" : "s"}`, "success");
      selection.mode = false;
      selection.ids.clear();
      container.querySelector("#select-toggle").classList.remove("btn-primary");
      container.querySelector("#add-item-fab").classList.remove("hidden");
      refreshItems(container, selection);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

function openBulkEditModal(container, selection) {
  const count = selection.ids.size;
  const { body, close } = openModalShell(`Edit ${count} item${count === 1 ? "" : "s"}`);

  body.innerHTML = `
    <div class="stack">
      <div class="field">
        <label class="row"><input type="checkbox" id="bulk-set-location" /> <span>Change location</span></label>
        <div class="field-row" id="bulk-location-fields" style="margin-top: var(--space-2);">
          <div class="field">
            <label for="bulk-room">Room</label>
            <input class="input" id="bulk-room" />
          </div>
          <div class="field">
            <label for="bulk-level">Level</label>
            <input class="input" id="bulk-level" />
          </div>
        </div>
        <div class="field" id="bulk-shelf-field">
          <label for="bulk-shelf">Shelf</label>
          <input class="input" id="bulk-shelf" />
        </div>
      </div>

      <div class="field">
        <label class="row"><input type="checkbox" id="bulk-set-quantity" /> <span>Change quantity</span></label>
        <div id="bulk-quantity-fields" style="margin-top: var(--space-2);">
          <div class="field">
            <label for="bulk-qty-type">Quantity type</label>
            <select class="select" id="bulk-qty-type">
              <option value="countable">Countable</option>
              <option value="uncountable">Uncountable</option>
            </select>
          </div>
          <div class="field" id="bulk-qty-countable-wrap">
            <label for="bulk-quantity">Quantity</label>
            <input class="input" type="number" min="0" id="bulk-quantity" />
          </div>
          <div class="field hidden" id="bulk-qty-uncountable-wrap">
            <label for="bulk-qty-note">Amount note</label>
            <input class="input" id="bulk-qty-note" placeholder="e.g. half bag" />
          </div>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-primary grow" id="bulk-save-btn">Apply to ${count} item${count === 1 ? "" : "s"}</button>
    </div>
  `;

  const setLocationCheckbox = body.querySelector("#bulk-set-location");
  const locationFields = body.querySelector("#bulk-location-fields");
  const shelfField = body.querySelector("#bulk-shelf-field");
  const syncLocationFields = () => {
    const on = setLocationCheckbox.checked;
    locationFields.style.opacity = on ? "1" : "0.4";
    shelfField.style.opacity = on ? "1" : "0.4";
    body.querySelector("#bulk-room").disabled = !on;
    body.querySelector("#bulk-level").disabled = !on;
    body.querySelector("#bulk-shelf").disabled = !on;
  };
  setLocationCheckbox.addEventListener("change", syncLocationFields);
  syncLocationFields();

  const setQuantityCheckbox = body.querySelector("#bulk-set-quantity");
  const quantityFields = body.querySelector("#bulk-quantity-fields");
  const qtyTypeSelect = body.querySelector("#bulk-qty-type");
  const countableWrap = body.querySelector("#bulk-qty-countable-wrap");
  const uncountableWrap = body.querySelector("#bulk-qty-uncountable-wrap");
  const syncQuantityFields = () => {
    const on = setQuantityCheckbox.checked;
    quantityFields.style.opacity = on ? "1" : "0.4";
    qtyTypeSelect.disabled = !on;
    body.querySelector("#bulk-quantity").disabled = !on;
    body.querySelector("#bulk-qty-note").disabled = !on;
  };
  const syncQtyTypeVisibility = () => {
    const isCountable = qtyTypeSelect.value === "countable";
    countableWrap.classList.toggle("hidden", !isCountable);
    uncountableWrap.classList.toggle("hidden", isCountable);
  };
  setQuantityCheckbox.addEventListener("change", syncQuantityFields);
  qtyTypeSelect.addEventListener("change", syncQtyTypeVisibility);
  syncQuantityFields();
  syncQtyTypeVisibility();

  body.querySelector("#bulk-save-btn").addEventListener("click", async () => {
    const setLocation = setLocationCheckbox.checked;
    const setQuantity = setQuantityCheckbox.checked;

    if (!setLocation && !setQuantity) {
      showToast("Choose at least one thing to change", "warning");
      return;
    }
    const room = body.querySelector("#bulk-room").value.trim();
    if (setLocation && !room) {
      showToast("Room is required to change location", "warning");
      return;
    }

    const payload = { item_ids: [...selection.ids] };
    payload.set_location = setLocation;
    if (setLocation) {
      payload.location = {
        room,
        level: body.querySelector("#bulk-level").value.trim() || null,
        shelf: body.querySelector("#bulk-shelf").value.trim() || null,
      };
    }
    payload.set_quantity = setQuantity;
    if (setQuantity) {
      const qtyType = qtyTypeSelect.value;
      payload.quantity_type = qtyType;
      payload.quantity = qtyType === "countable" ? Number(body.querySelector("#bulk-quantity").value || 0) : null;
      payload.quantity_note = qtyType === "uncountable" ? body.querySelector("#bulk-qty-note").value.trim() || null : null;
    }

    try {
      const result = await api.patch(`${CONFIG.STORAGE_BASE}/items/bulk`, payload);
      showToast(`Updated ${result.updated} item${result.updated === 1 ? "" : "s"}`, "success");
      selection.mode = false;
      selection.ids.clear();
      container.querySelector("#select-toggle").classList.remove("btn-primary");
      container.querySelector("#add-item-fab").classList.remove("hidden");
      close();
      refreshItems(container, selection);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

function renderPagination(root, container, selection) {
  const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  const currentPage = Math.floor(state.offset / PAGE_SIZE) + 1;

  root.innerHTML = "";
  if (state.total <= PAGE_SIZE) return;

  const wrap = document.createElement("div");
  wrap.className = "pagination";

  const prev = document.createElement("button");
  prev.className = "btn btn-icon";
  prev.innerHTML = icons.chevronLeft;
  prev.disabled = currentPage <= 1;
  prev.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    refreshItems(container, selection);
    container.querySelector(".page").scrollIntoView({ behavior: "smooth" });
  });

  const label = document.createElement("span");
  label.className = "page-label";
  label.textContent = `Page ${currentPage} of ${totalPages}`;

  const next = document.createElement("button");
  next.className = "btn btn-icon";
  next.innerHTML = icons.chevronRight;
  next.disabled = currentPage >= totalPages;
  next.addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    refreshItems(container, selection);
    container.querySelector(".page").scrollIntoView({ behavior: "smooth" });
  });

  wrap.append(prev, label, next);
  root.appendChild(wrap);
}

// --- Modals -----------------------------------------------------------

// Popup for picking a shelf, in place of a native <select> — shelf
// names are free text accumulated from items' locations, not a managed
// list, so this list has no inherent size cap the way Room's does; a
// search box keeps it usable on mobile regardless of how long it gets.
function openShelfPickerModal({ shelves, selected, onSelect }) {
  const { body, close } = openModalShell("Filter by shelf");
  body.innerHTML = `
    <div class="search-bar" style="margin-bottom: var(--space-3);">
      ${icons.search}
      <input type="search" id="sp-search" placeholder="Search shelves…" />
    </div>
    <div id="sp-list" class="stack" style="max-height: 55vh; overflow-y: auto;"></div>
  `;

  function pickerRow(label, isSelected) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "row-between";
    row.style.cssText =
      "width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-md); margin-bottom: var(--space-2); text-align: left; background: none; font: inherit; color: inherit;";
    row.innerHTML = `<span>${escapeHtml(label)}</span>${isSelected ? icons.check : ""}`;
    return row;
  }

  function renderList(q) {
    const listRoot = body.querySelector("#sp-list");
    const filtered = q ? shelves.filter((s) => s.toLowerCase().includes(q)) : shelves;
    listRoot.innerHTML = "";

    const anyRow = pickerRow("Any", !selected);
    anyRow.addEventListener("click", () => {
      onSelect("");
      close();
    });
    listRoot.appendChild(anyRow);

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No shelves match";
      listRoot.appendChild(empty);
      return;
    }

    filtered.forEach((shelf) => {
      const row = pickerRow(shelf, selected === shelf);
      row.addEventListener("click", () => {
        onSelect(shelf);
        close();
      });
      listRoot.appendChild(row);
    });
  }

  let debounceId = null;
  body.querySelector("#sp-search").addEventListener("input", (e) => {
    clearTimeout(debounceId);
    const q = e.target.value.trim().toLowerCase();
    debounceId = setTimeout(() => renderList(q), 150);
  });

  renderList("");
}

function openModalShell(titleText) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-header">
        <h2>${escapeHtml(titleText)}</h2>
        <button class="btn btn-icon btn-ghost" id="modal-close" aria-label="Close">${icons.close}</button>
      </div>
      <div id="modal-body"></div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector("#modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  const escHandler = (e) => {
    if (e.key === "Escape") {
      close();
      document.removeEventListener("keydown", escHandler);
    }
  };
  document.addEventListener("keydown", escHandler);

  return { overlay, body: overlay.querySelector("#modal-body"), close };
}

function openLightbox(src, alt) {
  const overlay = document.createElement("div");
  overlay.className = "lightbox-overlay";
  overlay.innerHTML = `
    <button class="lightbox-close" aria-label="Close">${icons.close}</button>
    <img src="${escapeAttr(src)}" alt="${escapeAttr(alt)}" />
  `;
  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target.closest(".lightbox-close")) close();
  });
  document.body.appendChild(overlay);
}

function itemFormHtml(item = {}) {
  const loc = item.location || {};
  return `
    <div class="stack">
      <div class="field">
        <label for="f-name">Name</label>
        <input class="input" id="f-name" value="${escapeAttr(item.name || "")}" required />
      </div>
      <div class="field">
        <label for="f-description">Description</label>
        <textarea class="input" id="f-description" rows="2">${escapeHtml(item.description || "")}</textarea>
      </div>
      <div class="field">
        <label for="f-aliases">Aliases (comma separated)</label>
        <input class="input" id="f-aliases" value="${escapeAttr((item.aliases || []).join(", "))}" />
      </div>
      <div class="field">
        <label for="f-qty-type">Quantity type</label>
        <select class="select" id="f-qty-type">
          <option value="countable" ${item.quantity_type !== "uncountable" ? "selected" : ""}>Countable</option>
          <option value="uncountable" ${item.quantity_type === "uncountable" ? "selected" : ""}>Uncountable</option>
        </select>
      </div>
      <div class="field" id="f-qty-countable-wrap">
        <label for="f-quantity">Quantity</label>
        <input class="input" type="number" min="0" id="f-quantity" value="${item.quantity ?? ""}" />
      </div>
      <div class="field" id="f-qty-uncountable-wrap">
        <label for="f-qty-note">Amount note</label>
        <input class="input" id="f-qty-note" placeholder="e.g. half bag" value="${escapeAttr(item.quantity_note || "")}" />
      </div>
      <div class="field">
        <label for="f-room">Room</label>
        <select class="select" id="f-room">
          <option value="">No room set</option>
          ${(roomsCache || [])
            .map(
              (r) =>
                `<option value="${escapeAttr(r.name)}" ${loc.room === r.name ? "selected" : ""}>${escapeHtml(r.name)}</option>`
            )
            .join("")}
        </select>
        ${(roomsCache || []).length === 0 ? `<span class="muted" style="font-size: var(--font-size-xs);">No rooms yet — add one in Settings → Manage rooms.</span>` : ""}
      </div>
      <div class="field-row">
        <div class="field">
          <label for="f-shelf">Shelf</label>
          <input class="input" id="f-shelf" value="${escapeAttr(loc.shelf || "")}" />
        </div>
        <div class="field">
          <label for="f-level">Shelf level</label>
          <input class="input" id="f-level" value="${escapeAttr(loc.level || "")}" />
        </div>
      </div>
      <div class="field">
        <label for="f-image">Photo</label>
        <input class="input" type="file" id="f-image" accept="image/png,image/jpeg,image/webp" />
      </div>
    </div>
  `;
}

function wireQtyTypeToggle(body) {
  const typeSelect = body.querySelector("#f-qty-type");
  const countableWrap = body.querySelector("#f-qty-countable-wrap");
  const uncountableWrap = body.querySelector("#f-qty-uncountable-wrap");
  const sync = () => {
    const isCountable = typeSelect.value === "countable";
    countableWrap.classList.toggle("hidden", !isCountable);
    uncountableWrap.classList.toggle("hidden", isCountable);
  };
  typeSelect.addEventListener("change", sync);
  sync();
}

function readItemForm(body) {
  const qtyType = body.querySelector("#f-qty-type").value;
  const aliases = body
    .querySelector("#f-aliases")
    .value.split(",")
    .map((a) => a.trim())
    .filter(Boolean);

  const room = body.querySelector("#f-room").value.trim();
  const level = body.querySelector("#f-level").value.trim();
  const shelf = body.querySelector("#f-shelf").value.trim();

  const payload = {
    name: body.querySelector("#f-name").value.trim(),
    description: body.querySelector("#f-description").value.trim() || null,
    aliases,
    quantity_type: qtyType,
    quantity: qtyType === "countable" ? Number(body.querySelector("#f-quantity").value || 0) : null,
    quantity_note: qtyType === "uncountable" ? body.querySelector("#f-qty-note").value.trim() || null : null,
    location: room ? { room, level: level || null, shelf: shelf || null } : null,
  };
  const imageInput = body.querySelector("#f-image");
  const imageFile = imageInput.files[0] || null;
  return { payload, imageFile };
}

function openItemModal(item, container) {
  const writable = canWrite();
  const { body, close } = openModalShell(item.name);

  const imageSection = item.image_path
    ? `<div class="item-thumb" id="modal-image" style="aspect-ratio: 4/3; border-radius: var(--radius-md); margin-bottom: var(--space-3); cursor: zoom-in;">${icons.image}</div>`
    : "";

  body.innerHTML = `
    ${imageSection}
    ${writable ? itemFormHtml(item) : readOnlyItemHtml(item)}
    ${
      writable
        ? `<div class="modal-footer">
             <button class="btn btn-danger" id="delete-btn">${icons.trash}<span>Delete</span></button>
             <button class="btn btn-primary grow" id="save-btn">Save changes</button>
           </div>`
        : ""
    }
  `;

  const modalImage = body.querySelector("#modal-image");
  if (modalImage) {
    const imageUrl = `${CONFIG.STORAGE_BASE}/items/${item.id}/image`;
    fetchImageUrl(imageUrl).then((objectUrl) => {
      if (!objectUrl) return;
      modalImage.innerHTML = "";
      const img = document.createElement("img");
      img.src = objectUrl;
      img.alt = item.name;
      modalImage.appendChild(img);
      modalImage.addEventListener("click", () => openLightbox(objectUrl, item.name));
    });
  }

  if (!writable) return;

  wireQtyTypeToggle(body);

  body.querySelector("#save-btn").addEventListener("click", async () => {
    const { payload, imageFile } = readItemForm(body);
    if (!payload.name) {
      showToast("Name is required", "warning");
      return;
    }
    try {
      await api.patch(`${CONFIG.STORAGE_BASE}/items/${item.id}`, payload);
      if (imageFile) {
        const fd = new FormData();
        fd.append("file", imageFile);
        await api.postForm(`${CONFIG.STORAGE_BASE}/items/${item.id}/image`, fd);
        invalidateImageUrl(`${CONFIG.STORAGE_BASE}/items/${item.id}/image`);
      }
      showToast("Item updated", "success");
      close();
      refreshItems(container);
    } catch {
      /* api.js already showed a toast */
    }
  });

  body.querySelector("#delete-btn").addEventListener("click", async () => {
    const ok = await showConfirmDialog({
      title: "Delete item",
      message: `Delete "${item.name}"? This can't be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.del(`${CONFIG.STORAGE_BASE}/items/${item.id}`);
      showToast("Item deleted", "success");
      close();
      refreshItems(container);
    } catch {
      /* api.js already showed a toast */
    }
  });
}

function readOnlyItemHtml(item) {
  return `
    <div class="stack">
      ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}
      <div class="row-between"><span class="muted">Quantity</span><span>${escapeHtml(quantityLabel(item))}</span></div>
      ${locationLabel(item) ? `<div class="row-between"><span class="muted">Location</span><span>${escapeHtml(locationLabel(item))}</span></div>` : ""}
      ${item.aliases && item.aliases.length ? `<div class="chip-row">${item.aliases.map((a) => `<span class="chip">${escapeHtml(a)}</span>`).join("")}</div>` : ""}
    </div>
  `;
}

function openAddModal(container) {
  const { body, close } = openModalShell("Add item");

  function renderForm() {
    body.innerHTML = `
      ${itemFormHtml()}
      <div class="modal-footer">
        <button class="btn grow" id="save-another-btn">Save &amp; add another</button>
        <button class="btn btn-primary grow" id="save-close-btn">Save &amp; close</button>
      </div>
    `;
    wireQtyTypeToggle(body);
    body.querySelector("#f-name").focus();
    body.querySelector("#save-close-btn").addEventListener("click", () => submit(false));
    body.querySelector("#save-another-btn").addEventListener("click", () => submit(true));
  }

  async function submit(addAnother) {
    const { payload, imageFile } = readItemForm(body);
    if (!payload.name) {
      showToast("Name is required", "warning");
      return;
    }
    // Remember room/level/shelf for the "add another" flow — bulk-adding
    // usually means several items from the same shelf.
    const stickyLocation = payload.location;

    try {
      const created = await api.post(`${CONFIG.STORAGE_BASE}/items`, payload);
      if (imageFile) {
        const fd = new FormData();
        fd.append("file", imageFile);
        await api.postForm(`${CONFIG.STORAGE_BASE}/items/${created.id}/image`, fd);
      }
      showToast(`Added "${created.name}"`, "success");

      if (addAnother) {
        renderForm();
        if (stickyLocation) {
          body.querySelector("#f-room").value = stickyLocation.room || "";
          body.querySelector("#f-level").value = stickyLocation.level || "";
          body.querySelector("#f-shelf").value = stickyLocation.shelf || "";
        }
        refreshItems(container);
      } else {
        close();
        refreshItems(container);
      }
    } catch {
      /* api.js already showed a toast */
    }
  }

  renderForm();
}

// --- tiny escaping helpers (this app has no templating engine) --------

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function escapeAttr(str) {
  return escapeHtml(str);
}

// A skeleton shown immediately flashes for anything that resolves fast
// (typical on a local network) — delaying when it's allowed to appear
// means a quick response never shows one at all, only a genuinely slow
// one does. Call this right before the request starts, then call the
// returned function as soon as it settles.
function showSkeletonAfterDelay(root, html, delayMs = 200) {
  const timer = setTimeout(() => {
    root.innerHTML = html;
  }, delayMs);
  return () => clearTimeout(timer);
}

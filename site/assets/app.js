// EatHalal — search, city filter, near-me sorting and the map.
// The restaurant cards are already in the HTML; this script only filters,
// reorders and annotates them, so the page still works without JavaScript.
(() => {
  "use strict";

  const data = window.RESTAURANTS || [];
  const byId = new Map(data.map((r) => [r.id, r]));
  const list = document.getElementById("cards");
  const cards = [...list.querySelectorAll(".card")];
  const originalOrder = cards.slice();
  const input = document.getElementById("q");
  const status = document.getElementById("status");
  const empty = document.getElementById("empty");
  const nearBtn = document.getElementById("near");
  const layout = document.querySelector(".layout");
  const chips = [...document.querySelectorAll(".chip")];
  const viewButtons = [...document.querySelectorAll(".view-toggle button")];

  const state = { q: "", city: "", me: null };

  // Accent-insensitive matching: "aija" finds "Äijä".
  const fold = (s) => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  cards.forEach((c) => { c._text = fold(c.dataset.search); });

  // --------------------------------------------------------------- filtering

  function distanceKm(a, b) {
    const R = 6371, rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const fmtKm = (km) => (km < 1 ? `${Math.round(km * 1000 / 50) * 50} m` : `${km < 10 ? km.toFixed(1) : Math.round(km)} km`);

  function apply() {
    const terms = fold(state.q).split(/\s+/).filter(Boolean);
    let shown = 0;
    const visibleIds = new Set();

    let ordered = originalOrder;
    if (state.me) {
      ordered = originalOrder.slice().sort((a, b) => (a._km ?? Infinity) - (b._km ?? Infinity));
    }
    ordered.forEach((c) => list.appendChild(c));

    for (const c of cards) {
      const ok = (!state.city || c.dataset.city === state.city) && terms.every((t) => c._text.includes(t));
      c.hidden = !ok;
      if (ok) { shown++; visibleIds.add(c.dataset.id); }
    }

    empty.hidden = shown > 0;
    const noun = shown === 1 ? "restaurant" : "restaurants";
    const where = state.city ? ` in ${state.city}` : "";
    const sort = state.me ? ", closest first" : "";
    status.innerHTML = shown === data.length && !state.q
      ? `Showing all <strong>${shown}</strong> ${noun}${sort}`
      : `<strong>${shown}</strong> ${noun}${where}${sort}`;

    map.update(visibleIds);
    syncUrl();
  }

  // ------------------------------------------------------------------ inputs

  let t;
  input.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = input.value.trim(); apply(); }, 120);
  });

  chips.forEach((chip) => chip.addEventListener("click", () => setCity(chip.dataset.city)));
  function setCity(city) {
    state.city = city;
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.city === city)));
    apply();
  }

  document.getElementById("reset").addEventListener("click", () => {
    input.value = ""; state.q = ""; setCity(""); input.focus();
  });

  viewButtons.forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  function setView(view) {
    layout.dataset.view = view;
    viewButtons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
    if (view === "map") map.ensure();
  }

  nearBtn.addEventListener("click", () => {
    if (state.me) { clearNear(); return; }
    if (!("geolocation" in navigator)) { say("Your browser can't share its location."); return; }
    nearBtn.setAttribute("aria-busy", "true");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        nearBtn.removeAttribute("aria-busy");
        state.me = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        nearBtn.setAttribute("aria-pressed", "true");
        nearBtn.querySelector("span").textContent = "Nearest first";
        for (const c of cards) {
          const r = byId.get(c.dataset.id);
          const badge = c.querySelector(".card-distance");
          if (r && r.lat != null) {
            c._km = distanceKm(state.me, r);
            badge.textContent = fmtKm(c._km);
            badge.hidden = false;
          }
        }
        map.showMe(state.me);
        apply();
        list.scrollIntoView({ behavior: "smooth", block: "start" });
      },
      (err) => {
        nearBtn.removeAttribute("aria-busy");
        say(err.code === err.PERMISSION_DENIED
          ? "Location is blocked. Allow it in your browser settings to sort by distance."
          : "Couldn't get your location. Try again in a moment.");
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
    );
  });

  function clearNear() {
    state.me = null;
    nearBtn.setAttribute("aria-pressed", "false");
    nearBtn.querySelector("span").textContent = "Near me";
    cards.forEach((c) => { c._km = undefined; c.querySelector(".card-distance").hidden = true; });
    map.showMe(null);
    apply();
  }

  function say(msg) { status.textContent = msg; }

  // Keep search and city in the URL so a filtered view can be shared.
  function syncUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.city) p.set("city", state.city);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  // --------------------------------------------------------------------- map

  const map = (() => {
    let m = null, markers = new Map(), meMarker = null, active = null, pending = null;
    const el = document.getElementById("map");
    const wide = window.matchMedia("(min-width: 1040px)");

    function ensure() {
      if (m) { m.invalidateSize(); return; }
      if (!window.L) { setTimeout(ensure, 150); return; }
      m = L.map(el, { scrollWheelZoom: false, zoomControl: true }).setView([62.5, 25.5], 5);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(m);
      m.on("focus", () => m.scrollWheelZoom.enable());
      m.on("blur", () => m.scrollWheelZoom.disable());

      for (const r of data) {
        if (r.lat == null) continue;
        const icon = L.divIcon({ className: "", html: '<div class="pin"></div>', iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -10] });
        const mk = L.marker([r.lat, r.lng], { icon, title: r.name, keyboard: true }).addTo(m);
        mk.bindPopup(popupHtml(r));
        mk.on("click", () => highlight(r.id, false));
        markers.set(r.id, mk);
      }
      update(pending || new Set(data.map((r) => r.id)));
    }

    function popupHtml(r) {
      const esc = (s) => (s || "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
      const dir = `https://www.google.com/maps/dir/?api=1&destination=${r.lat},${r.lng}`;
      const meta = [r.category, r.rating ? `★ ${r.rating.toFixed(1)}` : ""].filter(Boolean).join("  ");
      return `<p class="popup-name">${esc(r.name)}</p>` +
        (meta ? `<p class="popup-meta">${esc(meta)}</p>` : "") +
        (r.address ? `<p class="popup-address">${esc(r.address)}</p>` : "") +
        `<div class="popup-actions"><a class="popup-link" href="${dir}" target="_blank" rel="noopener">Directions</a>` +
        `<a class="popup-link" href="#r-${r.id}" data-goto="${r.id}">See details</a></div>`;
    }

    function update(ids) {
      pending = ids;
      if (!m) return;
      const pts = [];
      markers.forEach((mk, id) => {
        if (ids.has(id)) { mk.addTo(m); pts.push(mk.getLatLng()); } else { mk.remove(); }
      });
      if (meMarker) pts.push(meMarker.getLatLng());
      if (pts.length === 1) m.setView(pts[0], 14);
      else if (pts.length) m.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 14 });
    }

    function showMe(pos) {
      if (!m) { ensure(); setTimeout(() => showMe(pos), 200); return; }
      if (meMarker) { meMarker.remove(); meMarker = null; }
      if (pos) {
        const icon = L.divIcon({ className: "", html: '<div class="pin pin-me"></div>', iconSize: [18, 18], iconAnchor: [9, 9] });
        meMarker = L.marker([pos.lat, pos.lng], { icon, title: "You are here", interactive: false }).addTo(m);
      }
    }

    function highlight(id, fromList) {
      if (active) {
        document.getElementById(`r-${active}`)?.classList.remove("is-active");
        markers.get(active)?.getElement()?.firstChild?.classList.remove("is-active");
      }
      active = id;
      const card = document.getElementById(`r-${id}`);
      card?.classList.add("is-active");
      const mk = markers.get(id);
      mk?.getElement()?.firstChild?.classList.add("is-active");
      if (fromList && mk && m) { m.setView(mk.getLatLng(), Math.max(m.getZoom(), 14)); mk.openPopup(); }
      if (!fromList && wide.matches && card) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    // Clicking a card's empty space on wide screens pans the map to it.
    list.addEventListener("click", (e) => {
      if (!wide.matches || e.target.closest("a")) return;
      const card = e.target.closest(".card");
      if (card && card.dataset.lat) highlight(card.dataset.id, true);
    });
    // "See details" in a popup switches to the list on narrow screens.
    el.addEventListener("click", (e) => {
      const a = e.target.closest("[data-goto]");
      if (!a) return;
      e.preventDefault();
      if (!wide.matches) setView("list");
      highlight(a.dataset.goto, false);
      document.getElementById(`r-${a.dataset.goto}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    if (wide.matches) ensure();
    wide.addEventListener?.("change", (e) => { if (e.matches) ensure(); });
    return { ensure, update, showMe };
  })();

  // ------------------------------------------------------------------- start

  const params = new URLSearchParams(location.search);
  if (params.get("q")) { input.value = params.get("q"); state.q = input.value; }
  const city = params.get("city");
  if (city && chips.some((c) => c.dataset.city === city)) setCity(city); else apply();
})();

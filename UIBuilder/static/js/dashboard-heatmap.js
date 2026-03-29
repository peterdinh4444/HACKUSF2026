(function () {
  if (typeof window.L === "undefined") {
    return;
  }

  const onHubPage = !!document.getElementById("hub-heatmap-canvas");
  const mapElementId = onHubPage ? "hub-heatmap-canvas" : "dash-heatmap";
  const mapEl = document.getElementById(mapElementId);
  if (!mapEl) {
    return;
  }

  const ids = onHubPage
    ? {
        realtime: "hub-btn-realtime",
        mild: "hub-btn-mild",
        big: "hub-btn-big",
        status: "hub-sim-status",
      }
    : {
        realtime: "dash-btn-realtime",
        mild: "dash-btn-mild",
        big: "dash-btn-big",
        status: "dash-sim-status",
      };

  let currentSimulate = "";
  let heatLayer = null;

  // Constrain interaction to the Tampa Bay metro area.
  const tampaBounds = L.latLngBounds(
    [27.53, -82.85], // SW
    [28.36, -82.05]  // NE
  );

  const map = L.map(mapElementId, {
    maxBounds: tampaBounds,
    maxBoundsViscosity: 1.0,
    zoomControl: true,
  });

  map.fitBounds(tampaBounds);
  map.setMinZoom(map.getZoom());
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
  }).addTo(map);

  function removeHeatLayer() {
    if (heatLayer && map.hasLayer(heatLayer)) {
      map.removeLayer(heatLayer);
    }
    heatLayer = null;
  }

  function setStatus(text) {
    const statusEl = document.getElementById(ids.status);
    if (statusEl) {
      statusEl.textContent = text;
    }
  }

  function activateButton(activeId) {
    const buttonIds = [ids.realtime, ids.mild, ids.big];
    buttonIds.forEach((id) => {
      const btn = document.getElementById(id);
      if (!btn) return;
      if (id === activeId) btn.classList.add("btn--primary");
      else btn.classList.remove("btn--primary");
    });
  }

  function loadHeatMap() {
    removeHeatLayer();
    const query = currentSimulate ? `?simulate=${encodeURIComponent(currentSimulate)}&t=${Date.now()}` : `?t=${Date.now()}`;
    fetch(`/api/heatmap/data${query}`)
      .then((response) => response.json())
      .then((data) => {
        const heatData = Array.isArray(data.heat_data) ? data.heat_data : [];
        heatLayer = L.heatLayer(heatData, {
          radius: 25,
          blur: 15,
          maxZoom: 10,
          max: 1.0,
          gradient: {
            0.0: "blue",
            0.2: "lime",
            0.4: "yellow",
            0.6: "orange",
            1.0: "red",
          },
        }).addTo(map);
      })
      .catch(() => {
        mapEl.innerHTML = '<p class="panel__hint">Error loading map data. Please try again later.</p>';
      });
  }

  const realtimeBtn = document.getElementById(ids.realtime);
  const mildBtn = document.getElementById(ids.mild);
  const bigBtn = document.getElementById(ids.big);

  if (realtimeBtn) {
    realtimeBtn.addEventListener("click", function () {
      currentSimulate = "";
      setStatus("Currently showing real-time data.");
      activateButton(ids.realtime);
      loadHeatMap();
    });
  }

  if (mildBtn) {
    mildBtn.addEventListener("click", function () {
      currentSimulate = "mild";
      setStatus("Simulating mild storm conditions (+30 threat points).");
      activateButton(ids.mild);
      loadHeatMap();
    });
  }

  if (bigBtn) {
    bigBtn.addEventListener("click", function () {
      currentSimulate = "big";
      setStatus("Simulating big storm conditions (+70 threat points).");
      activateButton(ids.big);
      loadHeatMap();
    });
  }

  loadHeatMap();
})();

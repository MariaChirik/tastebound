import { DEFAULT_POINT } from "./logic.js";

const TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = "&copy; OpenStreetMap";

function leaflet() {
  return globalThis.L ?? null;
}

function baseMap(container, center, zoom = 13) {
  const L = leaflet();
  if (!L) return null;
  const map = L.map(container).setView([center.lat, center.lng], zoom);
  L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
  setTimeout(() => map.invalidateSize(), 50);
  return map;
}

function dot(L, color) {
  return { radius: 8, color, fillColor: color, fillOpacity: 0.9, weight: 2 };
}

export function pickerMap(container, point, onPick) {
  const L = leaflet();
  const map = baseMap(container, point ?? DEFAULT_POINT);
  if (!map) return null;
  let marker = point ? L.marker([point.lat, point.lng]).addTo(map) : null;
  const place = (lat, lng) => {
    if (marker) marker.setLatLng([lat, lng]);
    else marker = L.marker([lat, lng]).addTo(map);
  };
  map.on("click", (event) => {
    const picked = { lat: +event.latlng.lat.toFixed(6), lng: +event.latlng.lng.toFixed(6) };
    place(picked.lat, picked.lng);
    onPick(picked);
  });
  return {
    setPoint(picked) {
      place(picked.lat, picked.lng);
      map.setView([picked.lat, picked.lng], 16);
    },
    remove() {
      map.remove();
    },
  };
}

export function trackingMap(container, origin, destination) {
  const L = leaflet();
  const map = baseMap(container, origin);
  if (!map) return null;
  L.circleMarker([origin.lat, origin.lng], dot(L, "#b5452b")).addTo(map).bindTooltip("Ресторан");
  L.circleMarker([destination.lat, destination.lng], dot(L, "#2e7d4f"))
    .addTo(map)
    .bindTooltip("Адреса доставки");
  L.polyline([[origin.lat, origin.lng], [destination.lat, destination.lng]], {
    color: "#6d645c",
    dashArray: "6 6",
  }).addTo(map);
  map.fitBounds([[origin.lat, origin.lng], [destination.lat, destination.lng]], { padding: [30, 30] });
  let courier = null;
  return {
    moveCourier(point) {
      if (!point) return;
      if (courier) courier.setLatLng([point.lat, point.lng]);
      else courier = L.circleMarker([point.lat, point.lng], dot(L, "#2a5fa8")).addTo(map)
        .bindTooltip("Кур'єр");
    },
    remove() {
      map.remove();
    },
  };
}

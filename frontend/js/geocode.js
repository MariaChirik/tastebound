const NOMINATIM = "https://nominatim.openstreetmap.org";

export function formatAddress(result) {
  const a = result?.address ?? {};
  const street = [a.road ?? a.pedestrian ?? a.square, a.house_number].filter(Boolean).join(", ");
  const city = a.city ?? a.town ?? a.village ?? "";
  if (street) return city ? `${street}, ${city}` : street;
  return result?.display_name?.split(",").slice(0, 3).join(",").trim() ?? "";
}

export async function reverseGeocode(fetchImpl, lat, lng) {
  const params = new URLSearchParams({
    format: "jsonv2",
    lat: String(lat),
    lon: String(lng),
    "accept-language": "uk",
  });
  const response = await fetchImpl(`${NOMINATIM}/reverse?${params}`);
  if (!response.ok) return null;
  return formatAddress(await response.json()) || null;
}

export async function searchAddress(fetchImpl, query) {
  const params = new URLSearchParams({
    format: "jsonv2",
    q: query.includes("Київ") ? query : `${query}, Київ`,
    countrycodes: "ua",
    limit: "1",
    addressdetails: "1",
    "accept-language": "uk",
  });
  const response = await fetchImpl(`${NOMINATIM}/search?${params}`);
  if (!response.ok) return null;
  const [found] = await response.json();
  if (!found) return null;
  return { lat: +Number(found.lat).toFixed(6), lng: +Number(found.lon).toFixed(6) };
}

import { test } from "node:test";
import assert from "node:assert/strict";
import { formatAddress, reverseGeocode, searchAddress } from "../js/geocode.js";

function reply(body, ok = true) {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    return { ok, json: async () => body };
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

test("address is street, house and city", () => {
  const result = { address: { road: "вулиця Хрещатик", house_number: "22", city: "Київ" } };
  assert.equal(formatAddress(result), "вулиця Хрещатик, 22, Київ");
  assert.equal(formatAddress({ display_name: "Майдан, Київ, Україна, 01001" }), "Майдан, Київ, Україна");
  assert.equal(formatAddress(null), "");
});

test("map point becomes an address", async () => {
  const fetchImpl = reply({ address: { road: "вулиця Січових Стрільців", house_number: "5" } });
  assert.equal(await reverseGeocode(fetchImpl, 50.45, 30.5), "вулиця Січових Стрільців, 5");
  assert.match(fetchImpl.calls[0], /reverse\?format=jsonv2&lat=50.45&lon=30.5/);
});

test("typed address is searched in Kyiv", async () => {
  const fetchImpl = reply([{ lat: "50.4501234", lon: "30.5234567" }]);
  assert.deepEqual(await searchAddress(fetchImpl, "Хрещатик 22"), { lat: 50.450123, lng: 30.523457 });
  assert.match(decodeURIComponent(fetchImpl.calls[0]), /q=Хрещатик\+22,\+Київ/);
  assert.equal(await searchAddress(reply([]), "немає такої"), null);
  assert.equal(await searchAddress(reply(null, false), "збій"), null);
});

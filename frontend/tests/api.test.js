import { test } from "node:test";
import assert from "node:assert/strict";
import { createApi, ApiError } from "../js/api.js";

function fakeFetch(responses) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    const next = responses.shift();
    return {
      ok: next.status < 400,
      status: next.status,
      json: async () => {
        if (next.body === undefined) throw new SyntaxError("no body");
        return next.body;
      },
    };
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

test("login sends JSON to the auth service through the gateway", async () => {
  const fetchImpl = fakeFetch([{ status: 200, body: { token: "t", role: "client" } }]);
  const api = createApi(fetchImpl);
  const result = await api.login("ann@example.com", "strongpass1");
  assert.deepEqual(result, { token: "t", role: "client" });
  const { url, options } = fetchImpl.calls[0];
  assert.equal(url, "/api/auth/login");
  assert.equal(options.method, "POST");
  assert.deepEqual(JSON.parse(options.body), { email: "ann@example.com", password: "strongpass1" });
});

test("server error message becomes ApiError with the server text", async () => {
  const api = createApi(fakeFetch([{ status: 409, body: { error: "user already exists" } }]));
  await assert.rejects(api.register("a@b.com", "strongpass1", "client"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 409);
    assert.equal(err.message, "user already exists");
    return true;
  });
});

test("error without JSON body gets a generic message", async () => {
  const api = createApi(fakeFetch([{ status: 502 }]));
  await assert.rejects(api.dishes(""), (err) => err.message === "Помилка 502");
});

test("dishes query is appended to the catalog path", async () => {
  const fetchImpl = fakeFetch([{ status: 200, body: [] }]);
  await createApi(fetchImpl).dishes("?diet=vegan");
  assert.equal(fetchImpl.calls[0].url, "/api/catalog/dishes?diet=vegan");
});

test("token from getToken is sent as a Bearer header", async () => {
  const fetchImpl = fakeFetch([{ status: 200, body: [] }, { status: 200, body: [] }]);
  let token = null;
  const api = createApi(fetchImpl, () => token);
  await api.listOrders();
  token = "abc";
  await api.listOrders();
  assert.equal(fetchImpl.calls[0].options.headers.Authorization, undefined);
  assert.equal(fetchImpl.calls[1].options.headers.Authorization, "Bearer abc");
});

test("order is created with dish ids and delivery data only", async () => {
  const fetchImpl = fakeFetch([{ status: 201, body: { id: 1 } }]);
  const delivery = { address: "вул. Січова, 5", lat: 50.4, lng: 30.5, scheduled_for: 1800000000 };
  await createApi(fetchImpl).createOrder([{ dish_id: 3, quantity: 2 }], delivery);
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].options.body), {
    items: [{ dish_id: 3, quantity: 2 }],
    ...delivery,
  });
});

test("staff registration sends the chosen restaurant", async () => {
  const fetchImpl = fakeFetch([{ status: 201, body: { status: "pending" } }]);
  await createApi(fetchImpl).register("chef@hata.ua", "strongpass1", "restaurant_staff", "Хата");
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].options.body), {
    email: "chef@hata.ua",
    password: "strongpass1",
    role: "restaurant_staff",
    restaurant: "Хата",
  });
});

test("paths with user email are encoded", async () => {
  const fetchImpl = fakeFetch([
    { status: 200, body: { dishes: [] } },
    { status: 200, body: { items: [] } },
    { status: 200, body: {} },
  ]);
  const api = createApi(fetchImpl);
  await api.recommendations("ann@example.com", "?exclude_allergens=milk");
  await api.notifications("ann@example.com");
  await api.setUserStatus("chef@hata.ua", "active");
  assert.deepEqual(
    fetchImpl.calls.map((call) => call.url),
    [
      "/api/recommendations/recommendations/ann%40example.com?exclude_allergens=milk",
      "/api/notifications/users/ann%40example.com",
      "/api/auth/users/chef%40hata.ua/status",
    ],
  );
});

test("all routes match the gateway prefixes", async () => {
  const calls = [];
  const recordingApi = createApi(async (url, options) => {
    calls.push([options.method, url]);
    return { ok: true, status: 200, json: async () => ({}) };
  });
  await recordingApi.payOrder(1, "cash");
  await recordingApi.checkPayment(1);
  await recordingApi.advanceOrder(1);
  await recordingApi.cancelOrder(1);
  await recordingApi.createGroup();
  await recordingApi.setGroupItems("abc", []);
  await recordingApi.checkoutGroup("abc", {});
  await recordingApi.cancelGroup("abc");
  await recordingApi.location(1);
  await recordingApi.sendLocation(1, 50, 30);
  await recordingApi.menu();
  await recordingApi.updateDish(2, { available: false });
  await recordingApi.setOverload(true);
  await recordingApi.hideDish(2, true);
  assert.deepEqual(calls, [
    ["POST", "/api/orders/orders/1/pay"],
    ["POST", "/api/orders/orders/1/pay/check"],
    ["POST", "/api/orders/orders/1/advance"],
    ["POST", "/api/orders/orders/1/cancel"],
    ["POST", "/api/orders/groups"],
    ["PUT", "/api/orders/groups/abc/items"],
    ["POST", "/api/orders/groups/abc/checkout"],
    ["POST", "/api/orders/groups/abc/cancel"],
    ["GET", "/api/tracking/orders/1/location"],
    ["POST", "/api/tracking/orders/1/location"],
    ["GET", "/api/catalog/menu"],
    ["PATCH", "/api/catalog/menu/2"],
    ["POST", "/api/catalog/menu/overload"],
    ["POST", "/api/catalog/admin/dishes/2/hidden"],
  ]);
});

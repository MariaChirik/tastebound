export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function createApi(fetchImpl = globalThis.fetch, getToken = () => null) {
  async function request(method, path, body) {
    const options = { method, headers: {} };
    const token = getToken();
    if (token) options.headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetchImpl(path, options);
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (!response.ok) {
      throw new ApiError(response.status, data?.error ?? `Помилка ${response.status}`);
    }
    return data;
  }

  const enc = encodeURIComponent;

  return {
    register: (email, password, role, restaurant = "") =>
      request("POST", "/api/auth/register", { email, password, role, restaurant }),
    login: (email, password) => request("POST", "/api/auth/login", { email, password }),
    users: () => request("GET", "/api/auth/users"),
    setUserStatus: (email, status) =>
      request("POST", `/api/auth/users/${enc(email)}/status`, { status }),

    dishes: (query = "") => request("GET", `/api/catalog/dishes${query}`),
    restaurants: () => request("GET", "/api/catalog/restaurants"),
    menu: () => request("GET", "/api/catalog/menu"),
    addDish: (dish) => request("POST", "/api/catalog/menu", dish),
    updateDish: (id, fields) => request("PATCH", `/api/catalog/menu/${id}`, fields),
    setOverload: (overloaded) => request("POST", "/api/catalog/menu/overload", { overloaded }),
    adminDishes: () => request("GET", "/api/catalog/admin/dishes"),
    hideDish: (id, hidden) => request("POST", `/api/catalog/admin/dishes/${id}/hidden`, { hidden }),

    createOrder: (items, delivery) => request("POST", "/api/orders/orders", { items, ...delivery }),
    listOrders: () => request("GET", "/api/orders/orders"),
    getOrder: (id) => request("GET", `/api/orders/orders/${id}`),
    payOrder: (id, method) => request("POST", `/api/orders/orders/${id}/pay`, { method }),
    checkPayment: (id) => request("POST", `/api/orders/orders/${id}/pay/check`, {}),
    cancelOrder: (id) => request("POST", `/api/orders/orders/${id}/cancel`),
    advanceOrder: (id) => request("POST", `/api/orders/orders/${id}/advance`),
    createGroup: () => request("POST", "/api/orders/groups", {}),
    getGroup: (code) => request("GET", `/api/orders/groups/${enc(code)}`),
    setGroupItems: (code, items) =>
      request("PUT", `/api/orders/groups/${enc(code)}/items`, { items }),
    cancelGroup: (code) => request("POST", `/api/orders/groups/${enc(code)}/cancel`, {}),
    checkoutGroup: (code, delivery) =>
      request("POST", `/api/orders/groups/${enc(code)}/checkout`, delivery),

    location: (id) => request("GET", `/api/tracking/orders/${id}/location`),
    sendLocation: (id, lat, lng) =>
      request("POST", `/api/tracking/orders/${id}/location`, { lat, lng }),

    rate: (dish, score) => request("POST", "/api/recommendations/ratings", { dish, score }),
    ratings: (email) => request("GET", `/api/recommendations/ratings/${enc(email)}`),
    recommendations: (email, query = "") =>
      request("GET", `/api/recommendations/recommendations/${enc(email)}${query}`),

    notifications: (email) => request("GET", `/api/notifications/users/${enc(email)}`),
  };
}

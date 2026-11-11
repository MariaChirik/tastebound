import { createApi, ApiError } from "./api.js";
import { pickerMap, trackingMap } from "./map.js";
import {
  ALLERGENS,
  DIETS,
  ROLE_LABELS,
  ALL_ROLE_LABELS,
  USER_STATUS_LABELS,
  addToCart,
  canAddToCart,
  cartRestaurant,
  setQuantity,
  cartTotal,
  toOrderItems,
  formatPrice,
  formatTime,
  statusLabel,
  shareLabel,
  buildDishesQuery,
  isValidScore,
  isStaff,
  knownAllergens,
  allergenLabels,
  dietLabels,
  canCancel,
  staffAction,
  etaText,
  orderSummary,
  deliveredDishes,
  unseenCount,
  myShare,
  needsPayment,
  waitsForLiqpay,
  groupLink,
  parseGroupCode,
  itemsByUser,
  scheduleToUnix,
} from "./logic.js";

const STORAGE_NAME = "tastebound.v3";
const POLL_MS = 5000;
const VIEWS = ["catalog", "cart", "group", "orders", "work", "admin", "alerts", "recs", "account"];

function defaults() {
  return {
    token: null,
    email: null,
    role: null,
    restaurant: "",
    cart: [],
    allergens: [],
    seenAt: 0,
    delivery: { address: "", lat: null, lng: null },
    payMethod: "card",
    groupCode: null,
  };
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_NAME) ?? "{}");
    const state = { ...defaults(), ...saved };
    state.allergens = knownAllergens(state.allergens);
    return state;
  } catch {
    return defaults();
  }
}

const state = load();
const api = createApi(globalThis.fetch.bind(globalThis), () => state.token);
let currentView = "catalog";

function persist() {
  try {
    localStorage.setItem(STORAGE_NAME, JSON.stringify(state));
  } catch {
  }
}

// дані вставляються як текст, не як HTML
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (typeof value === "boolean" || key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function message(text, isError = false) {
  const box = document.getElementById("message");
  box.textContent = text;
  box.className = isError ? "message error" : "message";
}

function describe(err) {
  return err instanceof ApiError ? err.message : "Немає зв'язку із сервером. Спробуйте ще раз.";
}

function fail(err) {
  if (err instanceof ApiError && err.status === 401 && state.token) {
    logout("Сесія завершилася. Увійдіть знову.");
    return;
  }
  message(describe(err), true);
}

async function attempt(action) {
  try {
    return await action();
  } catch (err) {
    fail(err);
    return undefined;
  }
}

function roleKey() {
  return state.role ?? "guest";
}

function checkboxes(options, selected, name) {
  return el(
    "div",
    { class: "checks" },
    options.map((option) =>
      el(
        "label",
        {},
        el("input", {
          type: "checkbox",
          name,
          value: option.id,
          checked: selected.includes(option.id),
        }),
        option.label,
      ),
    ),
  );
}

function checkedValues(root, name) {
  return [...root.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value);
}

function updateNav() {
  const count = state.cart.reduce((sum, line) => sum + line.quantity, 0);
  document.getElementById("cart-count").textContent = String(count);
  document.getElementById("account-nav").textContent = state.email ?? "Вхід";
  for (const button of document.querySelectorAll("nav button[data-for]")) {
    button.hidden = !button.dataset.for.split(" ").includes(roleKey());
  }
}

function allowed(view) {
  const button = document.querySelector(`nav button[data-view="${view}"]`);
  return button && !button.hidden;
}

function homeView() {
  if (isStaff(state.role)) return "work";
  if (state.role === "admin") return "admin";
  return "catalog";
}

const renderers = {
  catalog: renderCatalog,
  cart: renderCart,
  group: renderGroup,
  orders: renderOrders,
  work: renderWork,
  admin: renderAdmin,
  alerts: renderAlerts,
  recs: renderRecs,
  account: renderAccount,
};

let cleanup = [];

function runCleanup() {
  for (const fn of cleanup) fn();
  cleanup = [];
}

function show(view) {
  if (!VIEWS.includes(view) || !allowed(view)) view = homeView();
  runCleanup();
  lastOrdersSignature = "";
  lastWorkSignature = "";
  lastGroupSignature = "";
  currentView = view;
  for (const name of VIEWS) {
    document.getElementById(`view-${name}`).hidden = name !== view;
  }
  for (const button of document.querySelectorAll("nav button")) {
    button.setAttribute("aria-current", button.dataset.view === view ? "page" : "false");
  }
  renderers[view]();
}

function renderDietOptions() {
  const select = document.getElementById("diet-select");
  if (select.options.length) return;
  for (const diet of DIETS) select.append(el("option", { value: diet.id }, diet.label));
}

function addDish(dish) {
  if (!canAddToCart(state.cart, dish)) {
    message(
      `У кошику страви з ресторану «${cartRestaurant(state.cart)}». ` +
        "Одне замовлення оформлюється з одного ресторану.",
      true,
    );
    return;
  }
  state.cart = addToCart(state.cart, dish);
  persist();
  updateNav();
  message(`Додано до кошика: ${dish.name}`);
}

function dishCard(dish, extra = null) {
  const allergens = dish.allergens.length ? allergenLabels(dish.allergens).join(", ") : "немає";
  const canBuy = roleKey() === "guest" || state.role === "client";
  return el(
    "article",
    { class: "card" },
    el("h3", {}, dish.name),
    el("p", { class: "muted" }, dish.restaurant),
    dish.composition ? el("p", {}, `Склад: ${dish.composition}`) : null,
    el("p", {}, `Алергени: ${allergens}`),
    dish.diets?.length ? el("p", { class: "muted" }, dietLabels(dish.diets).join(", ")) : null,
    extra,
    el("p", { class: "price" }, formatPrice(dish.price)),
    !dish.orderable
      ? el("p", { class: "note warn" }, "Ресторан тимчасово не приймає замовлення")
      : canBuy
        ? el("button", { type: "button", onclick: () => addDish(dish) }, "Додати")
        : null,
  );
}

async function renderCatalog() {
  renderDietOptions();
  const excluded = state.allergens;
  document.getElementById("profile-note").textContent = excluded.length
    ? `Ваші обмеження з профілю: ${allergenLabels(excluded).join(", ")}. Ці страви приховано.`
    : "Обмежень у профілі немає. Їх можна додати в розділі «Акаунт».";

  const grid = document.getElementById("dish-grid");
  grid.replaceChildren(el("p", {}, "Завантаження…"));
  try {
    const diet = document.getElementById("diet-select").value;
    const dishes = await api.dishes(buildDishesQuery({ excluded, diet }));
    grid.replaceChildren(
      ...(dishes.length
        ? dishes.map((dish) => dishCard(dish))
        : [el("p", {}, "За вашими обмеженнями страв немає.")]),
    );
  } catch (err) {
    grid.replaceChildren(el("p", { class: "message error" }, describe(err)));
  }
}

function deliveryForm() {
  const point = state.delivery.lat !== null ? state.delivery : null;
  const mapBox = el("div", { class: "map" });
  const coords = el(
    "p",
    { class: "note" },
    point ? `Точку на мапі обрано` : "Клацніть на мапі місце доставки.",
  );
  const address = el("input", {
    type: "text",
    placeholder: "Вулиця, будинок, квартира",
    value: state.delivery.address,
    oninput: (event) => {
      state.delivery.address = event.target.value;
      persist();
    },
  });
  const when = el("input", { type: "datetime-local", name: "scheduled" });
  const box = el(
    "div",
    { class: "panel" },
    el("h3", {}, "Доставка"),
    el("label", { class: "block" }, "Адреса", address),
    mapBox,
    coords,
    el(
      "label",
      { class: "block" },
      "Доставити на конкретний час (необов'язково)",
      when,
    ),
  );
  setTimeout(() => {
    const map = pickerMap(mapBox, point, (picked) => {
      Object.assign(state.delivery, picked);
      persist();
      coords.textContent = "Точку на мапі обрано";
    });
    if (map) cleanup.push(() => map.remove());
    else {
      mapBox.replaceChildren(el("p", { class: "note" }, "Мапа недоступна, використано центр міста."));
      if (state.delivery.lat === null) Object.assign(state.delivery, { lat: 50.4501, lng: 30.5234 });
    }
  });
  return {
    box,
    value() {
      if (state.delivery.address.trim().length < 3) {
        message("Вкажіть адресу доставки", true);
        return null;
      }
      if (state.delivery.lat === null) {
        message("Позначте місце доставки на мапі", true);
        return null;
      }
      const delivery = { ...state.delivery, address: state.delivery.address.trim() };
      const scheduled = scheduleToUnix(when.value);
      if (scheduled) delivery.scheduled_for = scheduled;
      return delivery;
    },
  };
}

function paymentChoice() {
  const options = [
    { id: "card", label: "Карткою онлайн (LiqPay, тестовий режим)" },
    { id: "cash", label: "Готівкою кур'єру" },
  ];
  return el(
    "div",
    { class: "panel" },
    el("h3", {}, "Оплата"),
    options.map((option) =>
      el(
        "label",
        { class: "block" },
        el("input", {
          type: "radio",
          name: "pay-method",
          value: option.id,
          checked: state.payMethod === option.id,
          onchange: () => {
            state.payMethod = option.id;
            persist();
          },
        }),
        option.label,
      ),
    ),
  );
}

function openLiqpay(checkout) {
  const form = el(
    "form",
    { method: "POST", action: checkout.url, target: "_blank", hidden: true },
    el("input", { type: "hidden", name: "data", value: checkout.data }),
    el("input", { type: "hidden", name: "signature", value: checkout.signature }),
  );
  document.body.append(form);
  form.submit();
  form.remove();
}

async function payShare(order, method = state.payMethod) {
  const result = await attempt(() => api.payOrder(order.id, method));
  if (!result) return null;
  if (result.checkout) {
    openLiqpay(result.checkout);
    message("Сторінку LiqPay відкрито в новій вкладці. Після оплати натисніть «Перевірити оплату».");
  } else if (method === "cash") {
    message(`Замовлення №${order.id}: оплата готівкою кур'єру.`);
  } else {
    message(`Частку замовлення №${order.id} оплачено.`);
  }
  return result.order;
}

function changeQuantity(id, quantity) {
  state.cart = setQuantity(state.cart, id, quantity);
  persist();
  updateNav();
  renderCart();
}

function cartLines() {
  return el(
    "ul",
    { class: "lines" },
    state.cart.map((line) =>
      el(
        "li",
        { class: "line" },
        el("span", {}, `${line.name} - ${formatPrice(line.price)}`),
        el("input", {
          type: "number",
          min: "1",
          max: "20",
          value: String(line.quantity),
          "aria-label": "Кількість",
          onchange: (event) => changeQuantity(line.id, Number(event.target.value)),
        }),
        el("button", { type: "button", onclick: () => changeQuantity(line.id, 0) }, "Видалити"),
      ),
    ),
  );
}

function renderCart() {
  runCleanup();
  const body = document.getElementById("cart-body");
  if (!state.cart.length) {
    body.replaceChildren(el("p", {}, "Кошик порожній."));
    return;
  }
  const isClient = state.role === "client";
  const summary = el(
    "div",
    { class: "panel" },
    el("h3", {}, `Ресторан «${cartRestaurant(state.cart)}»`),
    cartLines(),
    el("p", { class: "price" }, `Разом: ${formatPrice(cartTotal(state.cart))}`),
  );
  if (!isClient) {
    body.replaceChildren(summary, el("p", { class: "note" }, "Увійдіть як клієнт, щоб оформити замовлення."));
    return;
  }
  const delivery = deliveryForm();
  body.replaceChildren(
    el("div", { class: "columns" }, el("div", {}, summary, paymentChoice()), delivery.box),
    el(
      "div",
      { class: "row" },
      el(
        "button",
        { type: "button", class: "primary", onclick: (e) => placeOrder(e, delivery) },
        "Оформити і оплатити",
      ),
      el(
        "button",
        { type: "button", onclick: startGroupFromCart },
        "Зробити спільним: запросити колег",
      ),
    ),
  );
}

async function placeOrder(event, delivery) {
  const data = delivery.value();
  if (!data) return;
  const button = event.currentTarget;
  button.disabled = true;
  const order = await attempt(() => api.createOrder(toOrderItems(state.cart), data));
  if (!order) {
    button.disabled = false;
    return;
  }
  state.cart = [];
  persist();
  updateNav();
  await payShare(order);
  show("orders");
}

async function startGroupFromCart() {
  const group = await attempt(() => api.createGroup());
  if (!group) return;
  state.groupCode = group.code;
  persist();
  if (state.cart.length) {
    const updated = await attempt(() => api.setGroupItems(group.code, toOrderItems(state.cart)));
    if (updated) {
      state.cart = [];
      persist();
      updateNav();
    }
  }
  message("Спільне замовлення створено. Надішліть посилання колегам.");
  show("group");
}

async function joinGroup(code) {
  const group = await attempt(() => api.setGroupItems(code, toOrderItems(state.cart)));
  if (!group) return;
  state.cart = [];
  persist();
  updateNav();
  message("Ваші страви додано до спільного кошика.");
  renderGroup();
}

async function leaveGroupItems(code) {
  if (await attempt(() => api.setGroupItems(code, []))) renderGroup();
}

async function checkoutGroup(event, code, delivery) {
  const data = delivery.value();
  if (!data) return;
  event.currentTarget.disabled = true;
  const order = await attempt(() => api.checkoutGroup(code, data));
  if (!order) {
    event.currentTarget.disabled = false;
    return;
  }
  state.groupCode = null;
  persist();
  message(`Замовлення №${order.id} оформлено. Кожен учасник оплачує свою частку.`);
  show("orders");
}

function groupStartPanel() {
  return el(
    "div",
    { class: "panel" },
    el(
      "p",
      {},
      "Спільне замовлення дозволяє колегам додати страви в один кошик за посиланням. " +
        "Кожен оплачує свою частину, а доставка йде на одну адресу.",
    ),
    el(
      "button",
      { type: "button", class: "primary", onclick: startGroupFromCart },
      "Створити спільне замовлення",
    ),
  );
}

let lastGroupSignature = "";

async function renderGroup(force = true) {
  const body = document.getElementById("group-body");
  if (!state.groupCode) {
    body.replaceChildren(groupStartPanel());
    return;
  }
  const code = state.groupCode;
  let group;
  try {
    group = await api.getGroup(code);
  } catch (err) {
    state.groupCode = null;
    persist();
    body.replaceChildren(el("p", { class: "message error" }, describe(err)), groupStartPanel());
    return;
  }
  const signature = JSON.stringify([group.items, group.status]);
  if (!force && signature === lastGroupSignature) return;
  lastGroupSignature = signature;
  runCleanup();
  const link = groupLink(location.origin, code);
  const isOwner = group.owner === state.email;
  const byUser = itemsByUser(group.items);

  if (group.status !== "open") {
    body.replaceChildren(
      el("p", {}, `Замовлення №${group.order_id} вже оформлено. Оплатіть свою частку.`),
      el("button", { type: "button", class: "primary", onclick: () => show("orders") }, "Мої замовлення"),
    );
    state.groupCode = null;
    persist();
    return;
  }

  const participants = Object.entries(byUser).map(([user, items]) =>
    el(
      "div",
      { class: "panel" },
      el("h3", {}, user === state.email ? `${user} (ви)` : user),
      el("p", {}, items.map((i) => `${i.name} × ${i.quantity}`).join(", ")),
      el("p", { class: "price" }, `Частка: ${formatPrice(group.shares[user].amount)}`),
    ),
  );

  const cartNote = state.cart.length
    ? el(
        "button",
        { type: "button", class: "primary", onclick: () => joinGroup(code) },
        `Додати мій кошик (${formatPrice(cartTotal(state.cart))})`,
      )
    : el("p", { class: "note" }, "Додайте страви в кошик із каталогу, а потім поверніться сюди.");

  const parts = [
    el(
      "div",
      { class: "panel" },
      el("p", {}, `Організатор: ${group.owner}`),
      group.restaurant ? el("p", {}, `Ресторан: ${group.restaurant}`) : null,
      el("p", {}, "Посилання для колег:"),
      el("div", { class: "row" },
        el("input", { type: "text", readOnly: true, value: link, class: "grow" }),
        el("button", {
          type: "button",
          onclick: () => navigator.clipboard?.writeText(link).then(() => message("Посилання скопійовано")),
        }, "Копіювати"),
      ),
      el("p", { class: "price" }, `Разом: ${formatPrice(group.total)}`),
    ),
    el("div", { class: "grid" }, participants.length ? participants : el("p", {}, "Кошик поки порожній.")),
    el("div", { class: "row" },
      cartNote,
      byUser[state.email]
        ? el("button", { type: "button", onclick: () => leaveGroupItems(code) }, "Прибрати мої страви")
        : null,
    ),
  ];

  if (isOwner) {
    const delivery = deliveryForm();
    parts.push(
      delivery.box,
      el(
        "button",
        {
          type: "button",
          class: "primary",
          disabled: !group.items.length,
          onclick: (e) => checkoutGroup(e, code, delivery),
        },
        "Оформити спільне замовлення",
      ),
    );
  } else {
    parts.push(el("p", { class: "note" }, "Замовлення оформить організатор, після цього ви оплатите свою частку."));
  }
  body.replaceChildren(...parts);
}

const liveMaps = new Map();

function attachTracking(container, order) {
  const origin = { lat: order.restaurant_lat, lng: order.restaurant_lng };
  const destination = { lat: order.lat, lng: order.lng };
  setTimeout(async () => {
    const map = trackingMap(container, origin, destination);
    if (!map) {
      container.replaceChildren(el("p", { class: "note" }, "Мапа недоступна без інтернету."));
      return;
    }
    liveMaps.set(order.id, map);
    cleanup.push(() => {
      map.remove();
      liveMaps.delete(order.id);
    });
    await refreshCourier(order.id);
  });
}

async function refreshCourier(orderId) {
  const map = liveMaps.get(orderId);
  if (!map) return;
  try {
    const info = await api.location(orderId);
    map.moveCourier(info.courier);
  } catch {
  }
}

function sharesList(order) {
  return el(
    "ul",
    { class: "shares" },
    Object.entries(order.shares).map(([user, share]) =>
      el(
        "li",
        {},
        `${user === state.email ? "Ви" : user}: ${formatPrice(share.amount)} - ${shareLabel(share.status)}`,
      ),
    ),
  );
}

function orderCard(order, actions, withMap = false) {
  const mapBox = withMap ? el("div", { class: "map small" }) : null;
  const card = el(
    "article",
    { class: `card order-${order.status}` },
    el("h3", {}, `Замовлення №${order.id} - ${order.restaurant}`),
    el("p", { class: "muted" }, orderSummary(order)),
    el("p", {}, `Адреса: ${order.address} (${order.distance_km} км)`),
    el("p", {}, `Сума: ${formatPrice(order.total)}`),
    el("p", { class: "status" }, `Статус: ${statusLabel(order.status)}`),
    etaText(order) ? el("p", { class: "note" }, etaText(order)) : null,
    order.participants.length > 1 || order.status === "awaiting_payment" ? sharesList(order) : null,
    mapBox,
    el("div", { class: "row" }, actions),
  );
  if (mapBox) attachTracking(mapBox, order);
  return card;
}

async function act(action, rerender) {
  if ((await attempt(action)) !== undefined) rerender();
}

function clientActions(order) {
  const actions = [];
  if (needsPayment(order, state.email)) {
    const method = el(
      "select",
      {},
      el("option", { value: "card" }, "Карткою (LiqPay)"),
      el("option", { value: "cash" }, "Готівкою кур'єру"),
    );
    actions.push(
      method,
      el(
        "button",
        {
          type: "button",
          class: "primary",
          onclick: async () => {
            if (await payShare(order, method.value)) renderOrders(true);
          },
        },
        `Оплатити мою частку (${formatPrice(myShare(order, state.email).amount)})`,
      ),
    );
  }
  if (waitsForLiqpay(order, state.email)) {
    actions.push(
      el(
        "button",
        {
          type: "button",
          class: "primary",
          onclick: () => act(() => api.checkPayment(order.id), () => renderOrders(true)),
        },
        "Перевірити оплату",
      ),
    );
  }
  if (canCancel(order.status) && order.owner === state.email) {
    actions.push(
      el(
        "button",
        {
          type: "button",
          onclick: () =>
            act(
              () => api.cancelOrder(order.id),
              () => {
                message(`Замовлення №${order.id} скасовано. Оплачені кошти повертаються автоматично.`);
                renderOrders(true);
              },
            ),
        },
        "Скасувати",
      ),
    );
  }
  if (order.status === "delivered") {
    actions.push(el("button", { type: "button", onclick: () => show("recs") }, "Оцінити страви"));
  }
  return actions;
}

let lastOrdersSignature = "";

async function renderOrders(force = false) {
  const list = document.getElementById("order-list");
  const orders = await attempt(() => api.listOrders());
  if (!orders) return;
  const signature = JSON.stringify(orders.map((o) => [o.id, o.status, o.shares]));
  if (!force && signature === lastOrdersSignature && list.childElementCount) {
    for (const id of liveMaps.keys()) refreshCourier(id);
    return;
  }
  lastOrdersSignature = signature;
  runCleanup();
  if (!orders.length) {
    list.replaceChildren(el("p", {}, "Замовлень ще немає."));
    return;
  }
  list.replaceChildren(
    ...orders.map((order) => orderCard(order, clientActions(order), order.status === "delivering")),
  );
}

function dishRow(dish) {
  const allergenBox = checkboxes(ALLERGENS, dish.allergens, `allergens-${dish.id}`);
  const composition = el("input", { type: "text", value: dish.composition, class: "grow" });
  const save = async () => {
    const fields = {
      composition: composition.value,
      allergens: checkedValues(allergenBox, `allergens-${dish.id}`),
    };
    if (await attempt(() => api.updateDish(dish.id, fields))) message(`«${dish.name}» оновлено`);
  };
  return el(
    "div",
    { class: dish.available ? "dish-row" : "dish-row off" },
    el(
      "div",
      { class: "row" },
      el("strong", { class: "grow" }, `${dish.name} - ${formatPrice(dish.price)}`),
      dish.hidden ? el("span", { class: "note warn" }, "приховано модератором") : null,
      el(
        "label",
        {},
        el("input", {
          type: "checkbox",
          checked: dish.available,
          onchange: (event) =>
            act(
              () => api.updateDish(dish.id, { available: event.target.checked }),
              () => renderWork(true),
            ),
        }),
        "В наявності",
      ),
    ),
    el("div", { class: "row" }, el("span", {}, "Склад:"), composition),
    allergenBox,
    el("button", { type: "button", onclick: save }, "Зберегти склад і алергени"),
  );
}

function addDishForm() {
  const form = el(
    "form",
    {
      class: "panel",
      onsubmit: async (event) => {
        event.preventDefault();
        const dish = {
          name: form.elements.name.value,
          price: Number(form.elements.price.value),
          composition: form.elements.composition.value,
          allergens: checkedValues(form, "new-allergens"),
          diets: checkedValues(form, "new-diets"),
        };
        if (await attempt(() => api.addDish(dish))) {
          message(`Страву «${dish.name}» додано в меню`);
          renderWork(true);
        }
      },
    },
    el("h3", {}, "Нова страва"),
    el("input", { name: "name", placeholder: "Назва", required: true }),
    el("input", { name: "price", type: "number", min: "1", step: "0.01", placeholder: "Ціна, грн", required: true }),
    el("input", { name: "composition", placeholder: "Склад" }),
    el("p", { class: "note" }, "Алергени"),
    checkboxes(ALLERGENS, [], "new-allergens"),
    el("p", { class: "note" }, "Дієти"),
    checkboxes(DIETS.filter((d) => d.id), [], "new-diets"),
    el("button", { type: "submit", class: "primary" }, "Додати страву"),
  );
  return form;
}

async function restaurantMenuPanel() {
  const menu = await attempt(() => api.menu());
  if (!menu) return el("p", {}, "Меню недоступне.");
  const overloaded = menu.restaurant.overloaded;
  return el(
    "div",
    { class: "stack" },
    el(
      "div",
      { class: overloaded ? "panel alarm" : "panel" },
      el("h3", {}, "Режим перевантаження"),
      el(
        "p",
        {},
        overloaded
          ? "Нові замовлення не приймаються. Клієнти бачать, що ресторан тимчасово недоступний."
          : "Ресторан приймає замовлення.",
      ),
      el(
        "button",
        {
          type: "button",
          class: overloaded ? "primary" : "",
          onclick: () => act(() => api.setOverload(!overloaded), () => renderWork(true)),
        },
        overloaded ? "Знову приймати замовлення" : "Призупинити прийом замовлень",
      ),
    ),
    el("div", { class: "panel" }, el("h3", {}, "Меню і стоп-лист"), menu.dishes.map(dishRow)),
    addDishForm(),
  );
}

let watchId = null;
let sharingOrder = null;
let lastSent = 0;

function stopSharing() {
  if (watchId !== null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
  sharingOrder = null;
}

function startSharing(orderId) {
  if (!navigator.geolocation) {
    message("Браузер не дає доступу до геопозиції. Клієнт бачить розрахункове положення.", true);
    return;
  }
  stopSharing();
  sharingOrder = orderId;
  watchId = navigator.geolocation.watchPosition(
    (position) => {
      if (Date.now() - lastSent < POLL_MS) return;
      lastSent = Date.now();
      api
        .sendLocation(orderId, position.coords.latitude, position.coords.longitude)
        .catch(() => {});
    },
    () => message("Не вдалося отримати геопозицію. Клієнт бачить розрахункове положення.", true),
    { enableHighAccuracy: true },
  );
  message(`Геопозиція передається для замовлення №${orderId}`);
  renderWork(true);
}

function workActions(order) {
  const actions = [];
  const action = staffAction(state.role, order.status);
  if (action) {
    actions.push(
      el(
        "button",
        {
          type: "button",
          class: "primary",
          onclick: () =>
            act(
              async () => {
                const updated = await api.advanceOrder(order.id);
                if (updated.status === "delivered" && sharingOrder === order.id) stopSharing();
                message(`Замовлення №${order.id}: ${statusLabel(updated.status).toLowerCase()}`);
              },
              () => renderWork(true),
            ),
        },
        action,
      ),
    );
  }
  if (state.role === "courier") {
    const cash = Object.values(order.shares)
      .filter((share) => share.status === "cash_due")
      .reduce((sum, share) => sum + share.amount, 0);
    if (cash) actions.unshift(el("p", { class: "note warn" }, `Отримати готівкою: ${formatPrice(cash)}`));
    actions.push(
      sharingOrder === order.id
        ? el("button", { type: "button", onclick: () => { stopSharing(); renderWork(true); } }, "Зупинити геопозицію")
        : el("button", { type: "button", onclick: () => startSharing(order.id) }, "Ділитися геопозицією"),
    );
  }
  return actions;
}

let lastWorkSignature = "";

async function renderWork(force = false) {
  const isCourier = state.role === "courier";
  document.getElementById("work-title").textContent = isCourier
    ? "Кабінет кур'єра"
    : `Кабінет ресторану «${state.restaurant}»`;
  const body = document.getElementById("work-body");
  const orders = await attempt(() => api.listOrders());
  if (!orders) return;
  const signature = JSON.stringify(orders.map((o) => [o.id, o.status, o.shares]));
  if (!force && signature === lastWorkSignature && body.childElementCount) return;
  lastWorkSignature = signature;

  const list = orders.length
    ? orders.map((order) =>
        orderCard(order, [
          el("p", { class: "muted" }, `Клієнт: ${order.participants.join(", ")}`),
          ...workActions(order),
        ]),
      )
    : [el("p", {}, isCourier ? "Замовлень на доставку немає." : "Активних замовлень немає.")];

  const ordersPanel = el(
    "div",
    {},
    el("h3", {}, isCourier ? "Замовлення на доставку" : "Замовлення"),
    el("div", { class: "stack" }, list),
  );
  if (isCourier) {
    body.replaceChildren(ordersPanel);
    return;
  }
  body.replaceChildren(el("div", { class: "columns" }, ordersPanel, await restaurantMenuPanel()));
}

async function renderAdmin() {
  const body = document.getElementById("admin-body");
  const [users, dishes] = await Promise.all([
    attempt(() => api.users()),
    attempt(() => api.adminDishes()),
  ]);
  if (!users || !dishes) return;

  const userRows = users.map((user) => {
    const buttons = [];
    if (user.role !== "admin") {
      if (user.status !== "active") {
        buttons.push(
          el("button", {
            type: "button",
            class: "primary",
            onclick: () => act(() => api.setUserStatus(user.email, "active"), renderAdmin),
          }, user.status === "pending" ? "Підтвердити" : "Розблокувати"),
        );
      }
      if (user.status !== "blocked") {
        buttons.push(
          el("button", {
            type: "button",
            onclick: () => act(() => api.setUserStatus(user.email, "blocked"), renderAdmin),
          }, "Заблокувати"),
        );
      }
    }
    return el(
      "tr",
      { class: user.status === "pending" ? "highlight" : "" },
      el("td", {}, user.email),
      el("td", {}, ALL_ROLE_LABELS[user.role] ?? user.role),
      el("td", {}, user.restaurant || "-"),
      el("td", {}, USER_STATUS_LABELS[user.status] ?? user.status),
      el("td", {}, el("div", { class: "row" }, buttons)),
    );
  });

  const dishRows = dishes.map((dish) =>
    el(
      "tr",
      {},
      el("td", {}, dish.name),
      el("td", {}, dish.restaurant),
      el("td", {}, dish.composition || "-"),
      el("td", {}, dish.hidden ? "Приховано" : dish.available ? "Показується" : "Стоп-лист"),
      el(
        "td",
        {},
        el("button", {
          type: "button",
          onclick: () => act(() => api.hideDish(dish.id, !dish.hidden), renderAdmin),
        }, dish.hidden ? "Показати" : "Приховати"),
      ),
    ),
  );

  const table = (headers, rows) =>
    el("table", {}, el("thead", {}, el("tr", {}, headers.map((h) => el("th", {}, h)))), el("tbody", {}, rows));

  const pending = users.filter((user) => user.status === "pending").length;
  body.replaceChildren(
    el(
      "div",
      { class: "panel" },
      el("h3", {}, "Користувачі"),
      pending ? el("p", { class: "note warn" }, `Очікують підтвердження: ${pending}`) : null,
      table(["Email", "Роль", "Ресторан", "Стан", "Дії"], userRows),
    ),
    el(
      "div",
      { class: "panel" },
      el("h3", {}, "Модерація страв"),
      table(["Страва", "Ресторан", "Склад", "Стан", ""], dishRows),
    ),
  );
}

let latestAlerts = [];

async function refreshAlerts() {
  if (!state.email) return;
  try {
    latestAlerts = (await api.notifications(state.email)).items;
  } catch {
    return; // збій сповіщень не заважає роботі застосунку
  }
  const badge = document.getElementById("alerts-count");
  const unseen = currentView === "alerts" ? 0 : unseenCount(latestAlerts, state.seenAt);
  badge.textContent = String(unseen);
  badge.hidden = unseen === 0;
}

async function renderAlerts() {
  await refreshAlerts();
  const list = document.getElementById("alerts-list");
  list.replaceChildren(
    ...(latestAlerts.length
      ? latestAlerts.map((item) =>
          el(
            "li",
            { class: item.at > state.seenAt ? "alert new" : "alert" },
            el("span", { class: "muted" }, formatTime(item.at)),
            el("span", {}, item.message),
          ),
        )
      : [el("li", { class: "note" }, "Сповіщень поки немає.")]),
  );
  if (latestAlerts.length) {
    state.seenAt = Math.max(state.seenAt, latestAlerts[0].at);
    persist();
  }
  document.getElementById("alerts-count").hidden = true;
}

async function rateDish() {
  const dish = document.getElementById("rate-dish").value;
  const score = Number(document.getElementById("rate-score").value);
  if (!isValidScore(score)) {
    message("Оцінка має бути від 1 до 5", true);
    return;
  }
  if (await attempt(() => api.rate(dish, score))) {
    message(`Оцінку збережено: ${dish} - ${score}`);
    renderRecs();
  }
}

async function renderRecs() {
  const body = document.getElementById("rate-body");
  let orders = [];
  let ratings = {};
  let recommended = { dishes: [], available: true };
  try {
    [orders, ratings, recommended] = await Promise.all([
      api.listOrders(),
      api.ratings(state.email).then((data) => data.ratings),
      api.recommendations(state.email, buildDishesQuery({ excluded: state.allergens })),
    ]);
  } catch (err) {
    fail(err);
  }

  const dishes = deliveredDishes(orders, state.email);
  const rated = Object.entries(ratings);
  body.replaceChildren(
    el(
      "div",
      { class: "panel" },
      el("h3", {}, "Оцініть страву"),
      dishes.length
        ? el(
            "div",
            { class: "row" },
            el("select", { id: "rate-dish" }, dishes.map((d) => el("option", { value: d }, d))),
            el(
              "select",
              { id: "rate-score" },
              [5, 4, 3, 2, 1].map((n) => el("option", { value: String(n) }, `${n} ★`)),
            ),
            el("button", { type: "button", class: "primary", onclick: rateDish }, "Зберегти"),
          )
        : el("p", { class: "note" }, "Оцінити можна страви з доставлених замовлень."),
      rated.length
        ? el(
            "p",
            { class: "muted" },
            `Ваші оцінки: ${rated.map(([dish, score]) => `${dish} - ${score}`).join(", ")}`,
          )
        : null,
    ),
    el("h3", {}, "Вам сподобається"),
    recommended.dishes.length
      ? el(
          "div",
          { class: "grid" },
          recommended.dishes.map((dish) =>
            dishCard(dish, el("p", { class: "reason" }, `Чому: ${dish.reason}`)),
          ),
        )
      : el(
          "p",
          { class: "note" },
          recommended.available
            ? "Поки немає рекомендацій: оцініть страви на 4 або 5."
            : "Рекомендації тимчасово недоступні.",
        ),
  );
}

function allergenForm() {
  const box = checkboxes(ALLERGENS, state.allergens, "profile-allergens");
  box.addEventListener("change", () => {
    state.allergens = checkedValues(box, "profile-allergens");
    persist();
    message("Профіль оновлено");
  });
  return el(
    "div",
    { class: "panel" },
    el("h3", {}, "Обмеження з харчування"),
    el("p", { class: "note" }, "Позначте те, що вам не можна. Такі страви не показуватимуться."),
    box,
  );
}

async function login(email, password) {
  try {
    const result = await api.login(email, password);
    Object.assign(state, {
      token: result.token,
      role: result.role,
      restaurant: result.restaurant ?? "",
      email: email.trim().toLowerCase(),
      seenAt: 0,
    });
    persist();
    updateNav();
    message(`Ви увійшли як ${ALL_ROLE_LABELS[result.role] ?? result.role}`);
    refreshAlerts();
    show(state.groupCode && state.role === "client" ? "group" : homeView());
  } catch (err) {
    message(describe(err), true);
  }
}

async function register(form) {
  const email = form.elements.email.value.trim().toLowerCase();
  const pw = form.elements.password.value;
  const role = form.elements.role.value;
  const restaurant = form.elements.restaurant.value;
  let result;
  try {
    result = await api.register(email, pw, role, restaurant);
  } catch (err) {
    message(describe(err), true);
    return;
  }
  if (result.status === "pending") {
    message("Акаунт створено. Увійти можна після підтвердження адміністратором.");
    return;
  }
  await login(email, pw);
}

function logout(text = "Ви вийшли з акаунту") {
  stopSharing();
  Object.assign(state, { token: null, email: null, role: null, restaurant: "", seenAt: 0 });
  latestAlerts = [];
  persist();
  updateNav();
  message(text, text !== "Ви вийшли з акаунту");
  show("account");
}

function loginForm() {
  return el(
    "form",
    {
      class: "panel",
      onsubmit: (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        login(form.elements.email.value, form.elements.password.value);
      },
    },
    el("h3", {}, "Вхід"),
    el("input", { name: "email", type: "email", placeholder: "Email", required: true }),
    el("input", {
      name: "password",
      type: "password",
      placeholder: "Пароль",
      required: true,
      autocomplete: "current-password",
    }),
    el("button", { type: "submit", class: "primary" }, "Увійти"),
  );
}

function registerForm(restaurants) {
  const restaurantLabel = el(
    "label",
    { class: "block", hidden: true },
    "Ресторан",
    el("select", { name: "restaurant" }, restaurants.map((r) => el("option", { value: r.name }, r.name))),
  );
  const note = el("p", { class: "note" });
  return el(
    "form",
    {
      class: "panel",
      onsubmit: (event) => {
        event.preventDefault();
        register(event.currentTarget);
      },
    },
    el("h3", {}, "Реєстрація"),
    el("input", { name: "email", type: "email", placeholder: "Email", required: true }),
    el("input", {
      name: "password",
      type: "password",
      placeholder: "Пароль (мін. 8 символів)",
      required: true,
      minLength: 8,
      autocomplete: "new-password",
    }),
    el(
      "select",
      {
        name: "role",
        onchange: (event) => {
          const role = event.target.value;
          restaurantLabel.hidden = role !== "restaurant_staff";
          note.textContent =
            role === "client" ? "" : "Акаунт співробітника чи кур'єра підтверджує адміністратор.";
        },
      },
      Object.entries(ROLE_LABELS).map(([id, label]) => el("option", { value: id }, label)),
    ),
    restaurantLabel,
    note,
    el("button", { type: "submit" }, "Зареєструватися"),
  );
}

async function renderAccount() {
  const body = document.getElementById("account-body");
  if (state.email) {
    body.replaceChildren(
      el(
        "p",
        {},
        `Ви увійшли як ${state.email} (${ALL_ROLE_LABELS[state.role] ?? state.role}` +
          `${state.restaurant ? `, ${state.restaurant}` : ""})`,
      ),
      el("button", { type: "button", onclick: () => logout() }, "Вийти"),
      state.role === "client" ? el("div", { class: "forms" }, allergenForm()) : null,
    );
    return;
  }
  const restaurants = (await api.restaurants().catch(() => [])) ?? [];
  body.replaceChildren(
    state.groupCode
      ? el("p", { class: "note warn" }, "Увійдіть як клієнт, щоб приєднатися до спільного замовлення.")
      : null,
    el("div", { class: "forms" }, loginForm(), registerForm(restaurants)),
  );
}

function poll() {
  if (currentView === "orders") renderOrders();
  if (currentView === "work") renderWork();
  if (currentView === "group" && state.groupCode) renderGroup(false);
  if (currentView === "alerts") renderAlerts();
  else refreshAlerts();
}

function init() {
  for (const button of document.querySelectorAll("nav button")) {
    button.addEventListener("click", () => show(button.dataset.view));
  }
  document.getElementById("diet-select").addEventListener("change", renderCatalog);
  setInterval(poll, POLL_MS);

  updateNav();
  refreshAlerts();
  window.addEventListener("hashchange", () => openGroupLink() || show(location.hash.slice(1)));
  if (!openGroupLink()) show(location.hash.slice(1) || homeView());
}

function openGroupLink() {
  const code = parseGroupCode(location.hash);
  if (!code) return false;
  state.groupCode = code;
  persist();
  history.replaceState(null, "", location.pathname);
  show(state.role === "client" ? "group" : "account");
  return true;
}

init();

export const ALLERGENS = [
  { id: "gluten", label: "Глютен" },
  { id: "eggs", label: "Яйця" },
  { id: "fish", label: "Риба" },
  { id: "milk", label: "Молоко" },
  { id: "peanuts", label: "Арахіс" },
];

export const DIETS = [
  { id: "", label: "Будь-яка" },
  { id: "vegan", label: "Веганська" },
  { id: "vegetarian", label: "Вегетаріанська" },
  { id: "gluten_free", label: "Без глютену" },
];

export const ROLE_LABELS = {
  client: "Клієнт",
  restaurant_staff: "Співробітник ресторану",
  courier: "Кур'єр",
};

export const ALL_ROLE_LABELS = { ...ROLE_LABELS, admin: "Адміністратор" };

export const USER_STATUS_LABELS = {
  active: "Активний",
  pending: "Очікує підтвердження",
  blocked: "Заблокований",
};

// центр Києва
export const DEFAULT_POINT = { lat: 50.4501, lng: 30.5234 };

const STATUS_LABELS = {
  awaiting_payment: "Очікує оплати",
  created: "Прийнято рестораном",
  cooking: "Готується",
  delivering: "У дорозі",
  delivered: "Доставлено",
  cancelled: "Скасовано",
};

const SHARE_LABELS = {
  unpaid: "не оплачено",
  pending: "очікує підтвердження LiqPay",
  paid: "оплачено",
  cash_due: "готівкою кур'єру",
  failed: "оплата не пройшла",
  refunded: "кошти повернено",
  cancelled: "анульовано",
};

const STAFF_ACTIONS = {
  restaurant_staff: { created: "Почати готувати", cooking: "Передати кур'єру" },
  courier: { delivering: "Доставлено" },
};

export function buildDishesQuery({ excluded = [], diet = "" } = {}) {
  const params = new URLSearchParams();
  if (excluded.length) params.set("exclude_allergens", excluded.join(","));
  if (diet) params.set("diet", diet);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function knownAllergens(ids) {
  return ids.filter((id) => ALLERGENS.some((allergen) => allergen.id === id));
}

export function allergenLabels(ids) {
  return ids.map((id) => ALLERGENS.find((allergen) => allergen.id === id)?.label ?? id);
}

export function dietLabels(ids) {
  return ids.map((id) => DIETS.find((diet) => diet.id === id)?.label ?? id);
}

export function cartRestaurant(cart) {
  return cart[0]?.restaurant ?? null;
}

export function canAddToCart(cart, dish) {
  const restaurant = cartRestaurant(cart);
  return restaurant === null || restaurant === dish.restaurant;
}

export function addToCart(cart, dish) {
  if (cart.some((line) => line.id === dish.id)) {
    return cart.map((line) =>
      line.id === dish.id ? { ...line, quantity: line.quantity + 1 } : line,
    );
  }
  const { id, name, price, restaurant } = dish;
  return [...cart, { id, name, price, restaurant, quantity: 1 }];
}

export function setQuantity(cart, id, quantity) {
  if (!Number.isInteger(quantity) || quantity < 1) {
    return cart.filter((line) => line.id !== id);
  }
  return cart.map((line) => (line.id === id ? { ...line, quantity: Math.min(quantity, 20) } : line));
}

// у копійках, щоб не було похибок округлення
export function cartTotal(cart) {
  const cents = cart.reduce((sum, line) => sum + Math.round(line.price * 100) * line.quantity, 0);
  return cents / 100;
}

export function toOrderItems(cart) {
  return cart.map(({ id, quantity }) => ({ dish_id: id, quantity }));
}

export function formatPrice(value) {
  return `${value.toFixed(2)} грн`;
}

export function statusLabel(status) {
  return STATUS_LABELS[status] ?? "Невідомий статус";
}

export function shareLabel(status) {
  return SHARE_LABELS[status] ?? status;
}

export function canCancel(status) {
  return status === "awaiting_payment" || status === "created";
}

export function staffAction(role, status) {
  return STAFF_ACTIONS[role]?.[status] ?? null;
}

export function isStaff(role) {
  return role in STAFF_ACTIONS;
}

export function isValidScore(score) {
  return Number.isInteger(score) && score >= 1 && score <= 5;
}

export function myShare(order, email) {
  return order.shares?.[email] ?? null;
}

export function needsPayment(order, email) {
  const share = myShare(order, email);
  return order.status === "awaiting_payment" && ["unpaid", "failed"].includes(share?.status);
}

export function waitsForLiqpay(order, email) {
  return order.status === "awaiting_payment" && myShare(order, email)?.status === "pending";
}

function pad(n) {
  return String(n).padStart(2, "0");
}

function clockTime(seconds) {
  const date = new Date(seconds * 1000);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function dayAndTime(seconds) {
  const date = new Date(seconds * 1000);
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)} о ${clockTime(seconds)}`;
}

export function etaText(order) {
  if (order.status === "delivered") return "Замовлення доставлено";
  if (order.status === "cancelled") return null;
  if (order.scheduled) return `Доставка на ${dayAndTime(order.deliver_at)}`;
  return `Орієнтовна доставка о ${clockTime(order.deliver_at)} (≈${order.eta_minutes} хв)`;
}

export function orderSummary(order) {
  return order.items.map((item) => `${item.name} × ${item.quantity}`).join(", ");
}

export function deliveredDishes(orders, email) {
  const names = orders
    .filter((order) => order.status === "delivered")
    .flatMap((order) => order.items.filter((item) => !email || item.user === email))
    .map((item) => item.name);
  return [...new Set(names)];
}

export function groupLink(origin, code) {
  return `${origin}/#group=${encodeURIComponent(code)}`;
}

export function parseGroupCode(hash) {
  const match = /^#group=([\w-]+)$/.exec(hash ?? "");
  return match ? match[1] : null;
}

export function itemsByUser(items) {
  const result = {};
  for (const item of items) (result[item.user] ??= []).push(item);
  return result;
}

export function scheduleToUnix(value) {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : Math.round(time / 1000);
}

export function unseenCount(items, seenAt) {
  return items.filter((item) => item.at > seenAt).length;
}

export function formatTime(seconds) {
  return dayAndTime(seconds);
}

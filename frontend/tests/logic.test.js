import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildDishesQuery,
  addToCart,
  canAddToCart,
  cartRestaurant,
  setQuantity,
  cartTotal,
  toOrderItems,
  statusLabel,
  shareLabel,
  canCancel,
  isValidScore,
  knownAllergens,
  allergenLabels,
  staffAction,
  isStaff,
  etaText,
  orderSummary,
  deliveredDishes,
  unseenCount,
  needsPayment,
  waitsForLiqpay,
  groupLink,
  parseGroupCode,
  itemsByUser,
  scheduleToUnix,
} from "../js/logic.js";

const BORSCH = { id: 1, name: "Борщ", price: 135, restaurant: "Хата", allergens: [] };
const PASTA = { id: 5, name: "Паста", price: 190, restaurant: "Wok Kyiv", allergens: [] };

test("empty filters produce no query string", () => {
  assert.equal(buildDishesQuery(), "");
});

test("allergen exclusions and diet are encoded for the catalog", () => {
  assert.equal(
    buildDishesQuery({ excluded: ["gluten", "milk"], diet: "vegan" }),
    "?exclude_allergens=gluten%2Cmilk&diet=vegan",
  );
});

test("adding the same dish twice increases its quantity", () => {
  const cart = addToCart(addToCart([], BORSCH), BORSCH);
  assert.deepEqual(cart, [{ id: 1, name: "Борщ", price: 135, restaurant: "Хата", quantity: 2 }]);
});

test("cart accepts dishes from one restaurant only", () => {
  const cart = addToCart([], BORSCH);
  assert.equal(cartRestaurant(cart), "Хата");
  assert.equal(canAddToCart(cart, PASTA), false);
  assert.equal(canAddToCart([], PASTA), true);
});

test("quantity below one removes the line and is capped at 20", () => {
  const cart = addToCart([], BORSCH);
  assert.deepEqual(setQuantity(cart, 1, 0), []);
  assert.equal(setQuantity(cart, 1, 50)[0].quantity, 20);
});

test("total avoids floating point drift", () => {
  const cart = [{ id: 1, price: 0.1, quantity: 3 }];
  assert.equal(cartTotal(cart), 0.3);
});

test("order items carry only dish id and quantity, the server sets prices", () => {
  assert.deepEqual(toOrderItems([{ ...BORSCH, quantity: 2 }]), [{ dish_id: 1, quantity: 2 }]);
});

test("status and share labels follow the services", () => {
  assert.equal(statusLabel("awaiting_payment"), "Очікує оплати");
  assert.equal(statusLabel("delivering"), "У дорозі");
  assert.equal(statusLabel("unknown-value"), "Невідомий статус");
  assert.equal(shareLabel("cash_due"), "готівкою кур'єру");
});

test("cancellation is allowed only before cooking starts", () => {
  assert.equal(canCancel("awaiting_payment"), true);
  assert.equal(canCancel("created"), true);
  assert.equal(canCancel("cooking"), false);
  assert.equal(canCancel(null), false);
});

test("each role sees only its own next step", () => {
  assert.equal(staffAction("restaurant_staff", "created"), "Почати готувати");
  assert.equal(staffAction("restaurant_staff", "cooking"), "Передати кур'єру");
  assert.equal(staffAction("courier", "delivering"), "Доставлено");
  assert.equal(staffAction("courier", "created"), null);
  assert.equal(isStaff("courier"), true);
  assert.equal(isStaff("admin"), false);
});

test("participant pays only own unpaid or failed share", () => {
  const order = {
    status: "awaiting_payment",
    shares: {
      "ann@x.ua": { amount: 100, status: "paid" },
      "bob@x.ua": { amount: 50, status: "failed" },
      "eve@x.ua": { amount: 70, status: "pending" },
    },
  };
  assert.equal(needsPayment(order, "ann@x.ua"), false);
  assert.equal(needsPayment(order, "bob@x.ua"), true);
  assert.equal(needsPayment(order, "stranger@x.ua"), false);
  assert.equal(waitsForLiqpay(order, "eve@x.ua"), true);
  assert.equal(needsPayment({ ...order, status: "created" }, "bob@x.ua"), false);
});

test("eta text shows arrival time or the scheduled day", () => {
  const at = new Date(2026, 0, 1, 12, 33).getTime() / 1000;
  const order = { status: "cooking", deliver_at: at, eta_minutes: 33, scheduled: false };
  assert.equal(etaText(order), "Орієнтовна доставка о 12:33 (≈33 хв)");
  assert.equal(etaText({ ...order, scheduled: true }), "Доставка на 01.01 о 12:33");
  assert.equal(etaText({ ...order, status: "delivered" }), "Замовлення доставлено");
  assert.equal(etaText({ ...order, status: "cancelled" }), null);
});

test("only own dishes from delivered orders can be rated", () => {
  const orders = [
    {
      status: "delivered",
      items: [
        { name: "Рамен", quantity: 2, user: "ann" },
        { name: "Рис", quantity: 1, user: "bob" },
      ],
    },
    { status: "cooking", items: [{ name: "Піца", quantity: 1, user: "ann" }] },
  ];
  assert.equal(orderSummary(orders[0]), "Рамен × 2, Рис × 1");
  assert.deepEqual(deliveredDishes(orders, "ann"), ["Рамен"]);
});

test("group link round-trips through the address bar", () => {
  const link = groupLink("http://localhost:8080", "Ab3_x-9");
  assert.equal(link, "http://localhost:8080/#group=Ab3_x-9");
  assert.equal(parseGroupCode("#group=Ab3_x-9"), "Ab3_x-9");
  assert.equal(parseGroupCode("#orders"), null);
});

test("group items are grouped by participant", () => {
  const grouped = itemsByUser([
    { user: "ann", name: "A" },
    { user: "bob", name: "B" },
    { user: "ann", name: "C" },
  ]);
  assert.deepEqual(Object.keys(grouped), ["ann", "bob"]);
  assert.equal(grouped.ann.length, 2);
});

test("empty schedule means as soon as possible", () => {
  assert.equal(scheduleToUnix(""), null);
  assert.equal(scheduleToUnix("not a date"), null);
  assert.equal(scheduleToUnix("2026-01-01T12:00"), new Date(2026, 0, 1, 12, 0).getTime() / 1000);
});

test("scores are whole numbers from 1 to 5", () => {
  assert.equal(isValidScore(1), true);
  assert.equal(isValidScore(5), true);
  assert.equal(isValidScore(0), false);
  assert.equal(isValidScore(3.5), false);
});

test("unknown allergens are dropped and ids map to labels", () => {
  assert.deepEqual(knownAllergens(["gluten", "magic", "milk"]), ["gluten", "milk"]);
  assert.deepEqual(allergenLabels(["gluten", "peanuts"]), ["Глютен", "Арахіс"]);
});

test("only notifications newer than the last visit are unseen", () => {
  const items = [{ at: 30 }, { at: 20 }, { at: 10 }];
  assert.equal(unseenCount(items, 0), 3);
  assert.equal(unseenCount(items, 20), 1);
});

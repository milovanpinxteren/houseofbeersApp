/**
 * DEMO FIXTURE — only loaded when EXPO_PUBLIC_MOCK_ORDERS is set (never in
 * .env.production, and the dynamic import in getOrders keeps it out of real
 * bundles). Exercises every visual state of the orders screen:
 *
 * - two drafts (one with an embedded missed-items block, one with a custom
 *   no-variant line), a standalone missed card (rejected-only customer),
 * - orders covering all item states, the roll-up variants, every missed
 *   reason, the stale "alsnog geleverd ✓" case, and the period filter.
 */
import { OrdersResponse } from './orders';

/** ISO date `days` from now — keeps incoming/warehouse states stable. */
function daysFromNow(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

export const MOCK_ORDERS_RESPONSE: OrdersResponse = {
  drafts: [
    {
      id: '6795001',
      name: '#D6795',
      status: 'OPEN',
      created_at: daysAgoIso(2),
      invoice_url: 'https://houseofbeers.nl/invoices/demo',
      total_price: '43.80',
      currency: 'EUR',
      line_items: [
        {
          title: '26-10 - C - 3 Fonteinen – Oude Geuze',
          display_title: '3 Fonteinen – Oude Geuze',
          variant_title: 'Sale',
          quantity: 2,
          price: '12.95',
          product_id: 9001,
          state: 'in_warehouse',
          estimated_delivery_date: null,
        },
        {
          title: '26-10 - K - Perennial – BA Abraxas (2026)',
          display_title: 'Perennial – Barrel-Aged Abraxas (2026)',
          variant_title: 'Sale',
          quantity: 1,
          price: '17.90',
          product_id: 9002,
          state: 'incoming',
          estimated_delivery_date: daysFromNow(17),
        },
      ],
    },
    {
      id: '6801001',
      name: '#D6801',
      status: 'INVOICE_SENT',
      created_at: daysAgoIso(1),
      invoice_url: 'https://houseofbeers.nl/invoices/demo2',
      total_price: '18.50',
      currency: 'EUR',
      line_items: [
        {
          title: '28-10 - A - Moersleutel – Barcode Silver',
          display_title: 'Moersleutel – Barcode Silver',
          variant_title: 'Sale',
          quantity: 1,
          price: '14.50',
          product_id: 9010,
          state: 'in_warehouse',
          estimated_delivery_date: null,
        },
        {
          title: 'Statiegeld krat',
          display_title: 'Statiegeld krat',
          variant_title: null,
          quantity: 1,
          price: '4.00',
          product_id: null,
          state: 'unknown',
          estimated_delivery_date: null,
        },
      ],
    },
  ],

  missed: [
    // Attached to draft #D6795: one hard miss + one partial.
    {
      sale_id: 111,
      sale_name: '26-10',
      sale_date: daysFromNow(-3),
      draft_order_id: '6795001',
      shopify_order_id: null,
      lines: [
        {
          product_id: 9003,
          title: 'Perennial – Abraxas Taster 50 ml',
          requested: 1,
          received: 0,
          reason: 'out_of_stock',
        },
        {
          product_id: 9004,
          title: 'Westvleteren 12',
          requested: 3,
          received: 1,
          reason: 'max_per_customer',
        },
      ],
    },
    // Attached to order #HoB22371: a stale full miss (product 9101 IS in the
    // order's live lines → renders as "alsnog geleverd ✓") + a real miss.
    {
      sale_id: 109,
      sale_name: '19-10',
      sale_date: daysFromNow(-10),
      draft_order_id: null,
      shopify_order_id: '80001',
      lines: [
        {
          product_id: 9101,
          title: 'Cantillon – Lou Pepe Kriek 2019',
          requested: 1,
          received: 0,
          reason: 'out_of_stock',
        },
        {
          product_id: 9104,
          title: 'Side Project – Derivation #9',
          requested: 2,
          received: 0,
          reason: 'unavailable',
        },
      ],
    },
    // Standalone: a rejected-only customer's sale — no draft, no order.
    {
      sale_id: 110,
      sale_name: '24-10',
      sale_date: daysFromNow(-5),
      draft_order_id: null,
      shopify_order_id: null,
      lines: [
        {
          product_id: 9200,
          title: "Cantillon – Fou' Foune 2026",
          requested: 2,
          received: 0,
          reason: 'out_of_stock',
        },
      ],
    },
    // More standalone sales — the consolidated section must stay compact
    // even when many recent sales carry misses.
    {
      sale_id: 108,
      sale_name: '17-10',
      sale_date: daysFromNow(-12),
      draft_order_id: null,
      shopify_order_id: null,
      lines: [
        {
          product_id: 9201,
          title: 'Other Half – Double Citra Daydream',
          requested: 4,
          received: 2,
          reason: 'max_per_customer',
        },
      ],
    },
    {
      sale_id: 107,
      sale_name: '12-10',
      sale_date: daysFromNow(-17),
      draft_order_id: null,
      shopify_order_id: null,
      lines: [
        {
          product_id: 9202,
          title: 'Moersleutel – Missing Gear BA',
          requested: 1,
          received: 0,
          reason: 'out_of_stock',
        },
        {
          product_id: 9203,
          title: 'Frontaal – Golden Boy',
          requested: 1,
          received: 0,
          reason: 'unavailable',
        },
      ],
    },
    {
      sale_id: 106,
      sale_name: '05-10',
      sale_date: daysFromNow(-24),
      draft_order_id: null,
      shopify_order_id: null,
      lines: [
        {
          product_id: 9204,
          title: 'Azvex – Liquid Panda',
          requested: 2,
          received: 0,
          reason: 'out_of_stock',
        },
      ],
    },
  ],

  orders: [
    // Mixed states → three-segment roll-up; carries the missed block above.
    {
      id: 80001,
      order_number: 22371,
      name: '#HoB22371',
      created_at: daysAgoIso(9),
      financial_status: 'paid',
      fulfillment_status: 'partial',
      total_price: '86.40',
      currency: 'EUR',
      line_items: [
        {
          id: 1,
          title: '19-10 - B - Cantillon – Lou Pepe Kriek 2019',
          display_title: 'Cantillon – Lou Pepe Kriek 2019',
          variant_title: 'Sale',
          quantity: 1,
          price: '24.95',
          sku: null,
          product_id: 9101,
          fulfillment_status: null,
          state: 'in_warehouse',
          estimated_delivery_date: null,
        },
        {
          id: 2,
          title: '19-10 - D - 3 Fonteinen – Hommage 2024',
          display_title: '3 Fonteinen – Hommage 2024',
          variant_title: 'Sale',
          quantity: 2,
          price: '18.50',
          sku: null,
          product_id: 9102,
          fulfillment_status: null,
          state: 'in_warehouse',
          estimated_delivery_date: null,
        },
        {
          id: 3,
          title: '19-10 - F - Moersleutel – Indulgence 30',
          display_title: 'Moersleutel – Indulgence 30% Stout',
          variant_title: 'Sale',
          quantity: 1,
          price: '13.95',
          sku: null,
          product_id: 9103,
          fulfillment_status: null,
          state: 'incoming',
          estimated_delivery_date: daysFromNow(7),
        },
        {
          id: 4,
          title: 'Goose Island – Bourbon County 2025',
          display_title: 'Goose Island – Bourbon County 2025',
          variant_title: null,
          quantity: 1,
          price: '10.55',
          sku: null,
          product_id: 9105,
          fulfillment_status: 'fulfilled',
          state: 'shipped',
          estimated_delivery_date: null,
        },
      ],
    },
    // Everything shipped → single "Verzonden" roll-up.
    {
      id: 80002,
      order_number: 22290,
      name: '#HoB22290',
      created_at: daysAgoIso(16),
      financial_status: 'paid',
      fulfillment_status: 'fulfilled',
      total_price: '31.90',
      currency: 'EUR',
      line_items: [
        {
          id: 5,
          title: 'Nevel – Vlam',
          display_title: 'Nevel – Vlam',
          variant_title: null,
          quantity: 2,
          price: '15.95',
          sku: null,
          product_id: 9301,
          fulfillment_status: 'fulfilled',
          state: 'shipped',
          estimated_delivery_date: null,
        },
      ],
    },
    // Unpaid webshop order, everything on the shelf.
    {
      id: 80003,
      order_number: 22105,
      name: '#HoB22105',
      created_at: daysAgoIso(21),
      financial_status: 'pending',
      fulfillment_status: null,
      total_price: '27.85',
      currency: 'EUR',
      line_items: [
        {
          id: 6,
          title: 'Uiltje – Meneer de Uil',
          display_title: 'Uiltje – Meneer de Uil',
          variant_title: null,
          quantity: 3,
          price: '6.95',
          sku: null,
          product_id: 9401,
          fulfillment_status: null,
          state: 'in_warehouse',
          estimated_delivery_date: null,
        },
        {
          id: 7,
          title: 'Kees – Caramel Fudge Stout',
          display_title: 'Kees – Caramel Fudge Stout',
          variant_title: null,
          quantity: 1,
          price: '7.00',
          sku: null,
          product_id: 9402,
          fulfillment_status: null,
          state: 'in_warehouse',
          estimated_delivery_date: null,
        },
      ],
    },
    // Partial + unknown states, older order (period filter has work to do).
    {
      id: 80004,
      order_number: 21890,
      name: '#HoB21890',
      created_at: daysAgoIso(45),
      financial_status: 'paid',
      fulfillment_status: 'partial',
      total_price: '55.40',
      currency: 'EUR',
      line_items: [
        {
          id: 8,
          title: 'Frontaal – Blinding Lights',
          display_title: 'Frontaal – Blinding Lights',
          variant_title: null,
          quantity: 4,
          price: '9.95',
          sku: null,
          product_id: 9501,
          fulfillment_status: 'partial',
          state: 'partial',
          estimated_delivery_date: null,
        },
        {
          id: 9,
          title: 'Azvex – P(doom) Chocolate',
          display_title: 'Azvex – P(doom) Chocolate',
          variant_title: null,
          quantity: 1,
          price: '15.60',
          sku: null,
          product_id: 9502,
          fulfillment_status: null,
          state: 'unknown',
          estimated_delivery_date: null,
        },
      ],
    },
    // Last year → the period group grows year chips.
    {
      id: 80005,
      order_number: 18002,
      name: '#HoB18002',
      created_at: '2025-12-14T19:20:00+01:00',
      financial_status: 'paid',
      fulfillment_status: 'fulfilled',
      total_price: '64.00',
      currency: 'EUR',
      line_items: [
        {
          id: 10,
          title: 'Struise – Pannepot Reserva 2021',
          display_title: 'Struise – Pannepot Reserva 2021',
          variant_title: null,
          quantity: 4,
          price: '16.00',
          sku: null,
          product_id: 9601,
          fulfillment_status: 'fulfilled',
          state: 'shipped',
          estimated_delivery_date: null,
        },
      ],
    },
  ],
};

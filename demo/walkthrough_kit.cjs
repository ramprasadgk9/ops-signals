// Shared by the walkthrough recorders (demo/*/capture.cjs): captions, a focus outline and a
// visible mouse pointer drawn into the page, title cards, and pointer moves a viewer can follow.

// Captions, the focus outline and a visible mouse pointer (headless Chromium draws none), installed
// into every document the page loads, including the title cards.
const OVERLAY_SCRIPT = `
  (() => {
    const css = \`
      #demo-caption { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483646;
        padding: 16px 28px; background: rgba(17, 24, 39, 0.94); color: #fff; pointer-events: none;
        font: 600 23px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
      #demo-caption small { display: block; margin-top: 4px; font-weight: 400; font-size: 17px; color: #cbd5e1; }
      #demo-caption b { color: #fbbf24; }
      .demo-focus { outline: 3px solid #f59e0b !important; outline-offset: 4px; border-radius: 6px; }
      #demo-cursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; margin: -3px 0 0 -3px;
        pointer-events: none; transition: transform 120ms ease; left: -100px; top: -100px; }
      #demo-cursor.down { transform: scale(0.8); }
      .demo-ripple { position: fixed; z-index: 2147483646; width: 40px; height: 40px; margin: -20px 0 0 -20px;
        border-radius: 50%; border: 3px solid #f59e0b; pointer-events: none; animation: demo-ripple 500ms ease-out forwards; }
      @keyframes demo-ripple { from { transform: scale(0.3); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }
    \`;
    const install = () => {
      if (document.getElementById('demo-cursor')) return;
      const style = document.createElement('style');
      style.textContent = css;
      document.head.appendChild(style);
      const cursor = document.createElement('div');
      cursor.id = 'demo-cursor';
      cursor.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.body.appendChild(cursor);
      const last = window.__demoPointer;
      if (last) { cursor.style.left = last.x + 'px'; cursor.style.top = last.y + 'px'; }
      document.addEventListener('mousemove', (e) => {
        window.__demoPointer = { x: e.clientX, y: e.clientY };
        cursor.style.left = e.clientX + 'px';
        cursor.style.top = e.clientY + 'px';
      }, true);
      document.addEventListener('mousedown', (e) => {
        cursor.classList.add('down');
        const ripple = document.createElement('div');
        ripple.className = 'demo-ripple';
        ripple.style.left = e.clientX + 'px';
        ripple.style.top = e.clientY + 'px';
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);
      }, true);
      document.addEventListener('mouseup', () => cursor.classList.remove('down'), true);
    };
    if (document.body) install();
    else document.addEventListener('DOMContentLoaded', install);
  })();
`;

function card({ kicker, title, steps, footer }) {
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return `<!doctype html><meta charset="utf-8"><style>
    body { margin: 0; height: 100vh; display: grid; place-items: center; background: #0b1020; color: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    .wrap { width: 1040px; text-align: center; }
    .kicker { display: inline-block; padding: 6px 14px; border-radius: 999px; background: #0f766e; font-weight: 800; font-size: 16px; }
    h1 { margin: 22px 0 34px; font-size: 44px; line-height: 1.2; }
    ol { display: grid; grid-template-columns: repeat(${steps.length}, 1fr); gap: 18px; padding: 0; margin: 0; list-style: none; text-align: left; }
    li { padding: 22px; border-radius: 14px; background: #111827; border: 1px solid #1f2937; }
    li b { display: block; color: #fbbf24; font-size: 15px; letter-spacing: 0.04em; text-transform: uppercase; }
    li span { display: block; margin-top: 8px; font-size: 21px; font-weight: 700; }
    li em { display: block; margin-top: 6px; font-style: normal; color: #9ca3af; font-size: 16px; line-height: 1.4; }
    p { margin: 34px 0 0; color: #cbd5e1; font-size: 19px; }
    code { font-family: Menlo, Monaco, Consolas, monospace; color: #e5e7eb; }
  </style><div class="wrap"><span class="kicker">${escape(kicker)}</span><h1>${escape(title)}</h1><ol>${steps
    .map(([label, name, detail]) => `<li><b>${escape(label)}</b><span>${escape(name)}</span><em>${escape(detail)}</em></li>`)
    .join('')}</ol>${footer ? `<p>${footer}</p>` : ''}</div>`;
}

async function caption(page, title, detail) {
  await page.evaluate(
    ([t, d]) => {
      document.getElementById('demo-caption')?.remove();
      const el = document.createElement('div');
      el.id = 'demo-caption';
      el.innerHTML = t;
      if (d) {
        const small = document.createElement('small');
        small.textContent = d;
        el.appendChild(small);
      }
      document.body.appendChild(el);
    },
    [title, detail || ''],
  );
}

async function focus(page, locator) {
  await page.evaluate(() => document.querySelectorAll('.demo-focus').forEach((el) => el.classList.remove('demo-focus')));
  if (locator) await locator.evaluate((el) => el.classList.add('demo-focus'));
}

// Scrolls the element to a comfortable spot above the caption bar.
async function bringIntoView(page, locator, offset = 140) {
  await locator.evaluate((el, top) => {
    let scroller = el.parentElement;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight && /(auto|scroll)/.test(getComputedStyle(scroller).overflowY))) {
      scroller = scroller.parentElement;
    }
    const target = scroller || document.scrollingElement;
    const delta = el.getBoundingClientRect().top - (scroller ? scroller.getBoundingClientRect().top : 0) - top;
    target.scrollBy({ top: delta, behavior: 'smooth' });
  }, offset);
  await page.waitForTimeout(900);
}

async function pointAt(page, locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('element to point at is not visible');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 });
  await page.waitForTimeout(250);
}

async function clickOn(page, locator) {
  await pointAt(page, locator);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
}

module.exports = { OVERLAY_SCRIPT, card, caption, focus, bringIntoView, pointAt, clickOn };

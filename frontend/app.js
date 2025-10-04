/* ====== Konfigurace API ======
 * Backend: POST /chat {question:"..."} -> {answer:"..."}
 */
const API_BASE  = "http://localhost:8000";
const API_URL   = `${API_BASE}/chat`;
/* Kde hostuješ soubory náhledů (relativní cesty se napojí sem).
 * Pokud obrázky servíruje UI (Vite/NGINX), dej ASSET_BASE = window.location.origin
 */
const ASSET_BASE = `${API_BASE}`;

/* ====== Elementy ====== */
const chatWindow = document.getElementById("chatWindow");
const chatForm   = document.getElementById("chatForm");
const chatInput  = document.getElementById("chatMessage");
const sendBtn    = chatForm?.querySelector("button");

/* ====== Dekorace (pokud existují) ====== */
try {
  if (typeof initStarfield === "function") initStarfield();
  if (typeof scatterRunes  === "function") scatterRunes();
} catch (e) {
  console.warn("[UI] Dekorace nešly inicializovat:", e);
}

/* ====== Start zpráva ====== */
addBubble(
  "Mohu pomoci s následujícími úkoly:\n\n1. Vyhledávání a zobrazení I/O adres pro konkrétní ventily podle jejich TAGu.\n2. Vytvoření seznamu ventilů podle prefixu TAGu.\n3. Vyhledávání výkresů, kde se vyskytují specifické TAGy.\n4. Získání aktuálního stavu systému a posledních událostí.\n\nPokud máš konkrétní dotaz nebo úkol, dej mi vědět!",
  "bot",
  { rich: true }
);

/* ====== Odeslání zprávy ====== */
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  if (text.toLowerCase() === "/clear") {
    console.log("[UI] /clear -> čistím okno");
    chatWindow.innerHTML = "";
    addBubble("Pergamen je čistý. Pokračuj…", "bot");
    chatInput.value = "";
    return;
  }

  addBubble(text, "user");
  chatInput.value = "";
  let typingBubble;

  try {
    if (sendBtn) sendBtn.disabled = true;
    typingBubble = addTypingBubble();

    console.log("[REQ] →", API_URL, { question: text });
    const t0 = performance.now();

    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text })
    });

    if (!res.ok) {
      const body = await res.text().catch(()=>"(nelze číst tělo)");
      console.error("[ERR] HTTP", res.status, body);
      removeTypingBubble(typingBubble);
      addBubble(`Chyba serveru (${res.status}).`, "bot");
      return;
    }

    const data = await res.json().catch((e)=>{
      console.error("[ERR] JSON parse:", e);
      return null;
    });

    const t1 = performance.now();
    console.log(`[REQ] ← ${Math.round(t1 - t0)} ms`, data);

    removeTypingBubble(typingBubble);
    const answer = (data && (data.answer ?? data.message ?? data.text)) || "(prázdná odpověď)";
    addBubble(answer, "bot", { rich: true });
  } catch (err) {
    console.error("[ERR] fetch:", err);
    removeTypingBubble(typingBubble);
    addBubble("Nepodařilo se spojit s API.", "bot");
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    chatInput.focus();
  }
});

/* ====== Bubliny ====== */
function addBubble(text, who = "bot", opts = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = `bubble ${who}`;

  const content = document.createElement("div");
  content.className = "bubble-content";

  if (opts.rich) {
    console.log("[RENDER] raw", text);
    renderRichText(text, content);
  } else {
    content.textContent = text;
  }

  wrapper.appendChild(content);
  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  console.log("[UI] Bubble added:", { who, chars: text?.length ?? 0 });
}

/* ====== Typing bublina ====== */
function addTypingBubble() {
  const b = document.createElement("div");
  b.className = "bubble bot typing";
  b.innerHTML = `
    <div class="typing-dot"></div>
    <div class="typing-dot"></div>
    <div class="typing-dot"></div>
  `;
  chatWindow.appendChild(b);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return b;
}
function removeTypingBubble(el) {
  if (el && el.parentNode) el.remove();
}

/* ====== Renderer (Markdown lite + chytré URL) ====== */
function renderRichText(src, mount) {
  try {
    const blocks = normalizeNewlines(src).split(/\n{2,}/);

    for (const block of blocks) {
      // 1) Přímé MD obrázky: ![alt](url)
      const imgMd = block.match(/!\[([^\]]*)\]\(([^)]+)\)/i);
      if (imgMd) {
        const url = extractUrl(imgMd[2]);
        if (url && isImageUrl(url)) {
          mount.appendChild(makeImage(url, imgMd[1]));
          continue;
        }
      }

      // 2) Řádek s textem "Náhled" / "[Náhled]" nebo samostatný řádek s URL v závorkách
      const looksLikePreview = /(?:^\s*\[?\s*n[áa]hled\s*\]?\s*$)/i.test(block);
      const loneUrl = extractUrl(block); // umí (relative), <...>, http i prosté 'data/...'
      if (loneUrl && isImageUrl(loneUrl) && (looksLikePreview || onlyContainsUrl(block))) {
        mount.appendChild(makeImage(loneUrl, "náhled"));
        continue;
      }

      // 3) Obyč odstavce s inliny
      const p = document.createElement("p");
      transformInline(block, p);
      mount.appendChild(p);
    }
    console.log("[RENDER] done");
  } catch (e) {
    console.error("[ERR] renderRichText:", e);
    mount.textContent = src;
  }
}

function transformInline(text, parent) {
  let rest = text;
  const patterns = [
    { type: "img",  re: /!\[([^\]]*)\]\(([^)]+)\)/i },
    { type: "link", re: /\[([^\]]+)\]\(([^)]+)\)/i },
    { type: "url",  re: /(?:https?:\/\/\S+|(?:\.{0,2}\/)?[A-Za-z0-9_\-]+(?:\/[\w.\-/%]+)+)/i } // http(s) i relativní cesta se slash
  ];

  while (rest.length) {
    let earliest = null;
    let which = null;

    for (const p of patterns) {
      const m = rest.match(p.re);
      if (m && (!earliest || m.index < earliest.index)) {
        earliest = m;
        which = p.type;
      }
    }

    if (!earliest) {
      parent.appendChild(document.createTextNode(rest));
      break;
    }

    if (earliest.index > 0) {
      parent.appendChild(document.createTextNode(rest.slice(0, earliest.index)));
    }

    if (which === "img") {
      const alt = earliest[1];
      const url = extractUrl(earliest[2]);
      if (url) parent.appendChild(makeImage(url, alt));
    } else if (which === "link") {
      const label = earliest[1];
      const url = extractUrl(earliest[2]);
      if (url) parent.appendChild(makeLink(url, label));
      else parent.appendChild(document.createTextNode(label));
    } else if (which === "url") {
      const url = extractUrl(earliest[0]);
      if (url) {
        if (isImageUrl(url)) parent.appendChild(makeImage(url, "náhled"));
        else parent.appendChild(makeLink(url, url));
      } else {
        parent.appendChild(document.createTextNode(earliest[0]));
      }
    }

    rest = rest.slice(earliest.index + earliest[0].length);
  }
}

/* ====== Helpery URL/obrázky ====== */
function makeLink(href, text) {
  try {
    const a = document.createElement("a");
    a.href = resolveUrl(href);
    a.textContent = text;
    a.target = "_blank";
    a.rel = "noopener";
    return a;
  } catch (e) {
    console.warn("[RENDER] bad link:", href, e);
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  }
}

function makeImage(src, alt = "") {
  const img = document.createElement("img");
  img.src = resolveUrl(src);
  img.alt = alt || "preview";
  img.className = "preview-img";
  img.loading = "lazy";
  img.decoding = "async";
  img.addEventListener("error", () => {
    console.warn("[RENDER] image error:", src);
    img.replaceWith(makeLink(src, "(odkaz na obrázek)"));
  });
  return img;
}

/* Vytáhne URL z textu: http(s), (url), <url>, nebo relativní „data/...“ */
function extractUrl(text) {
  if (!text) return null;
  const s = String(text).trim();

  // 1) http(s)
  const mHttp = s.match(/https?:\/\/\S+/);
  if (mHttp) return stripWrappers(mHttp[0]);

  // 2) (relative-or-http) – uvnitř závorek
  const mParen = s.match(/\(([^()\s][^()]*)\)/);
  if (mParen) return stripWrappers(mParen[1]);

  // 3) <...>
  const mAngle = s.match(/<([^<>\s][^<>]*)>/);
  if (mAngle) return stripWrappers(mAngle[1]);

  // 4) holá relativní cesta se slash
  const mRel = s.match(/(?:^|\s)((?:\.{0,2}\/)?[A-Za-z0-9_\-]+(?:\/[\w.\-/%]+)+)/);
  if (mRel) return stripWrappers(mRel[1]);

  return null;
}
function stripWrappers(u) {
  return String(u).trim().replace(/^["']|["']$/g, "");
}

/* Dovolíme http(s), root-relative i relativní cesty → přemapujeme na ASSET_BASE */
function resolveUrl(u) {
  const s = String(u).trim();
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith("/")) return `${window.location.origin}${s}`;
  // jinak relativní – napojíme na ASSET_BASE
  return `${ASSET_BASE.replace(/\/$/, "")}/${s.replace(/^\.?\//, "")}`;
}

function isImageUrl(u) {
  return /\.(png|jpg|jpeg|gif|webp|bmp|svg)(\?|#|$)/i.test(String(u));
}
function normalizeNewlines(s) {
  return String(s).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

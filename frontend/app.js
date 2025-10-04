/* ====== Konfigurace API ======
 * Backend: POST /chat {question: "..."} -> {answer: "..."}
 */
const API_URL = "http://localhost:8000/chat"; // uprav dle svého routeru

const chatWindow = document.getElementById("chatWindow");
const chatForm   = document.getElementById("chatForm");
const chatInput  = document.getElementById("chatMessage");

/* Inicializace dekorací */
initStarfield();
scatterRunes();

/* Uvítací zpráva */
addBubble("Vítej, poutníku. Co dnes budeme kouzlit?", "bot");

/* Odeslání zprávy */
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  if (text.toLowerCase() === "/clear") {
    chatWindow.innerHTML = "";
    addBubble("Pergamen je čistý. Pokračuj…", "bot");
    chatInput.value = "";
    return;
  }

  addBubble(text, "user");
  chatInput.value = "";

  // placeholder “kouzlení”
  const thinking = addBubble("•••", "bot", true);

  try {
    // Volání API (FastAPI /chat očekává {question: "..."} )
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text })
    });

    if (!res.ok) throw new Error("HTTP " + res.status);

    const data = await res.json();
    thinking.remove();

    // API vrací "answer"; necháme i pojistné fallbacky
    const reply =
      data.answer ??
      data.reply ??
      data.message ??
      "(Tiché šelestění pergamenu…)";

    addBubble(reply, "bot");
  } catch (err) {
    thinking.remove();
    addBubble("Magie selhala při vyvolávání odpovědi. (Zkus nastavit API_URL nebo backend.)", "bot");
    console.error(err);
  }
});

/* Přidání bubliny do okna */
function addBubble(text, who = "bot", isEphemeral = false) {
  const b = document.createElement("div");
  b.className = `bubble ${who}`;
  b.textContent = text;
  chatWindow.appendChild(b);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  if (isEphemeral) b.dataset.ephemeral = "1";
  return b;
}

/* ====== Starfield (Canvas) ====== */
function initStarfield() {
  const canvas = document.getElementById("starfield");
  const ctx = canvas.getContext("2d");
  let w, h, stars;

  function resize() {
    w = canvas.width = window.innerWidth * devicePixelRatio;
    h = canvas.height = window.innerHeight * devicePixelRatio;
    stars = createStars(Math.floor((w * h) / (12000 * devicePixelRatio)));
  }

  function createStars(n) {
    const arr = [];
    for (let i = 0; i < n; i++) {
      arr.push({
        x: Math.random() * w,
        y: Math.random() * h,
        z: Math.random() * 0.6 + 0.4,
        tw: Math.random() * 2 * Math.PI,
        sp: Math.random() * 0.2 + 0.02
      });
    }
    return arr;
  }

  function draw() {
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      s.tw += s.sp;
      const alpha = 0.6 + Math.sin(s.tw) * 0.35;
      ctx.globalAlpha = alpha;
      const r = s.z * 1.2 + 0.2;
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
      ctx.fill();

      // pomalý drift
      s.x += s.z - 0.7;
      if (s.x > w + 10) s.x = -10;
    }
    requestAnimationFrame(draw);
  }

  window.addEventListener("resize", resize);
  resize();
  requestAnimationFrame(draw);
}

/* Rozmístění “run” náhodně po obrazovce */
function scatterRunes() {
  const runes = document.querySelectorAll(".runes span");
  runes.forEach((r) => {
    r.style.left = `${Math.random() * 100}%`;
    r.style.top = `${Math.random() * 100}%`;
    r.style.animationDelay = `${(Math.random() * 6).toFixed(2)}s`;
  });
}

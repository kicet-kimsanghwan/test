// 센텀시티 구내식당 대시보드 - 프론트엔드
// menus.json을 읽어 식당 카드를 렌더링한다.

const SOURCE_LABEL = { kakao: "카카오 채널", naver: "네이버 블로그" };

async function load() {
  try {
    // 캐시 회피용 쿼리스트링
    const res = await fetch(`data/menus.json?t=${Date.now()}`);
    const data = await res.json();
    render(data);
  } catch (e) {
    document.getElementById("updated").textContent = "데이터를 불러오지 못했습니다.";
    console.error(e);
  }
}

function fmtUpdated(iso) {
  if (!iso) return "아직 수집 전";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ` +
         `${p(d.getHours())}:${p(d.getMinutes())} 업데이트`;
}

function dateLabel(r) {
  if (r.type === "weekly" && r.weekOf) return `${r.weekOf} 주간`;
  if (r.date) return r.date;
  return "";
}

function card(r) {
  const el = document.createElement("div");
  el.className = "card";

  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML = `<h3>${r.name}</h3><span class="card-date">${dateLabel(r)}</span>`;
  el.appendChild(head);

  if (r.images && r.images.length) {
    const box = document.createElement("div");
    box.className = "imgs";
    r.images.forEach((src) => {
      const img = document.createElement("img");
      img.src = src;
      img.alt = `${r.name} 메뉴`;
      img.loading = "lazy";
      img.addEventListener("click", () => openModal(src, r.name));
      box.appendChild(img);
    });
    el.appendChild(box);
  } else {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = r.note || "메뉴 사진이 아직 없습니다.";
    el.appendChild(empty);
  }

  const foot = document.createElement("div");
  foot.className = "card-foot";
  const warn = (r.note && r.images && r.images.length === 0)
    ? `<span class="warn">⚠ 자동 수집 실패</span>` : "";
  foot.innerHTML =
    `<span class="src-tag">${SOURCE_LABEL[r.source] || r.source}</span>` +
    `<span>${warn} <a href="${r.sourceUrl}" target="_blank" rel="noopener">원문 보기 ↗</a></span>`;
  el.appendChild(foot);
  return el;
}

function render(data) {
  document.getElementById("updated").textContent = fmtUpdated(data.updatedAt);
  const daily = document.getElementById("daily");
  const weekly = document.getElementById("weekly");
  daily.innerHTML = "";
  weekly.innerHTML = "";
  (data.restaurants || []).forEach((r) => {
    (r.type === "weekly" ? weekly : daily).appendChild(card(r));
  });
}

// 모달
const modal = document.getElementById("modal");
const modalImg = document.getElementById("modalImg");
function openModal(src, alt) {
  modalImg.src = src;
  modalImg.alt = alt;
  modal.hidden = false;
}
function closeModal() { modal.hidden = true; modalImg.src = ""; }
document.getElementById("modalClose").addEventListener("click", closeModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

load();

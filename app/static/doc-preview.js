/* ดูตัวอย่างเอกสารบนหน้าเว็บ (routers/approval_flow.py + services/doc_preview.py)
   <div data-dp-inline="URL">        แสดงในหน้าเลย (หน้าเรื่องของ ผอ.)
   <button data-dp-open="URL">       เปิดเป็นหน้าต่างลอย (ก่อนกดส่ง ผอ.)
   URL ไม่มี doc = รายชื่อเอกสาร {docs:[{key,label,file}]}  URL&doc=คีย์ = {ok,pages:[ภาพ],total,cut,msg} */
(function () {
  var ZOOMS = [50, 75, 100, 125, 150, 200];

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function withDoc(url, key) {
    return url + (url.indexOf("?") >= 0 ? "&" : "?") + "doc=" + encodeURIComponent(key);
  }
  function getJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function Viewer(host, url, scrollInside) {
    var root = el("div", "dpv" + (scrollInside ? " dpv-in" : ""));
    var tabs = el("div", "dpv-tabs");
    var bar = el("div", "dpv-bar");
    var pages = el("div", "dpv-pages");
    root.appendChild(tabs); root.appendChild(bar); root.appendChild(pages);
    host.innerHTML = ""; host.appendChild(root);

    var zi = 2, figs = [], obs = null, seq = 0;
    bar.innerHTML =
      '<span class="dpv-pg">หน้า <input type="number" min="1" value="1" inputmode="numeric"> / <b>-</b></span>' +
      '<span class="dpv-zoom"><button type="button" data-z="-1" title="ย่อ">−</button><span>100%</span>' +
      '<button type="button" data-z="1" title="ขยาย">+</button></span>' +
      '<a class="dpv-dl" href="#" hidden>ดาวน์โหลด Word</a>';
    var pgIn = bar.querySelector("input"), pgTot = bar.querySelector(".dpv-pg b"),
        zLbl = bar.querySelector(".dpv-zoom span"), dl = bar.querySelector(".dpv-dl");
    bar.style.visibility = "hidden";

    function applyZoom() {
      zLbl.textContent = ZOOMS[zi] + "%";
      pages.style.setProperty("--dpz", ZOOMS[zi] / 100);
    }
    bar.querySelectorAll("[data-z]").forEach(function (b) {
      b.addEventListener("click", function () {
        zi = Math.max(0, Math.min(ZOOMS.length - 1, zi + (+b.dataset.z)));
        applyZoom();
      });
    });
    pgIn.addEventListener("change", function () {
      var n = Math.max(1, Math.min(figs.length, parseInt(pgIn.value, 10) || 1));
      pgIn.value = n;
      if (figs[n - 1]) figs[n - 1].scrollIntoView({ behavior: "smooth", block: "start" });
    });
    applyZoom();

    function msg(text, file) {
      pages.innerHTML = "";
      var m = el("div", "dpv-msg");
      m.textContent = text;
      if (file) { var a = el("a", "btn sm gray", "ดาวน์โหลด Word"); a.href = file; m.appendChild(el("br")); m.appendChild(a); }
      pages.appendChild(m);
    }

    function show(d, btn) {
      var my = ++seq;
      tabs.querySelectorAll("button").forEach(function (b) { b.classList.toggle("on", b === btn); });
      bar.style.visibility = "hidden";
      if (d.file) { dl.href = d.file; dl.hidden = false; } else dl.hidden = true;
      pages.innerHTML = '<div class="dpv-msg"><span class="dpv-spin"></span> กำลังสร้างตัวอย่าง ' +
        (d.label || "") + " รอสักครู่</div>";
      getJSON(withDoc(url, d.key)).then(function (r) {
        if (my !== seq) return;
        if (!r.ok) { msg(r.msg || "สร้างตัวอย่างไม่สำเร็จ", d.file); return; }
        pages.innerHTML = ""; figs = [];
        if (obs) obs.disconnect();
        var n = r.pages.length;
        obs = "IntersectionObserver" in window ? new IntersectionObserver(function (es) {
          es.forEach(function (e) { if (e.isIntersecting) pgIn.value = e.target.dataset.n; });
        }, { root: scrollInside ? pages : null, rootMargin: "-45% 0px -50% 0px" }) : null;
        r.pages.forEach(function (src, i) {
          var f = el("figure", "dpv-page"); f.dataset.n = i + 1;
          var img = el("img"); img.src = src; img.alt = "หน้า " + (i + 1); img.loading = i < 2 ? "eager" : "lazy";
          f.appendChild(img);
          f.appendChild(el("figcaption", "", "หน้า " + (i + 1) + " / " + r.total));
          pages.appendChild(f); figs.push(f);
          if (obs) obs.observe(f);
        });
        if (r.cut) pages.appendChild(el("div", "dpv-msg", "แสดง " + n + " หน้าแรกจาก " + r.total + " หน้า ดาวน์โหลดเพื่อดูทั้งหมด"));
        pgIn.max = n; pgIn.value = 1; pgTot.textContent = r.total;
        bar.style.visibility = "";
        pages.scrollTop = 0;
      }).catch(function () { if (my === seq) msg("โหลดตัวอย่างไม่สำเร็จ ลองใหม่อีกครั้ง", d.file); });
    }

    pages.innerHTML = '<div class="dpv-msg"><span class="dpv-spin"></span> กำลังโหลด</div>';
    getJSON(url).then(function (r) {
      var docs = r.docs || [];
      if (!docs.length) { msg(r.msg || "เรื่องนี้ยังไม่มีเอกสารของขั้นนี้"); return; }
      docs.forEach(function (d, i) {
        var b = el("button", "", ""); b.type = "button"; b.textContent = d.label;
        b.addEventListener("click", function () { show(d, b); });
        tabs.appendChild(b);
        if (i === 0) show(d, b);
      });
      if (docs.length < 2) tabs.classList.add("dpv-one");
    }).catch(function () { msg("โหลดรายชื่อเอกสารไม่สำเร็จ"); });
  }

  function openModal(url, title) {
    var ov = el("div", "dpv-ov");
    var box = el("div", "dpv-box");
    var head = el("div", "dpv-head");
    head.appendChild(el("b", "", ""));
    head.firstChild.textContent = title || "ตัวอย่างเอกสาร";
    var x = el("button", "dpv-x", "✕"); x.type = "button"; x.title = "ปิด";
    head.appendChild(x);
    var body = el("div", "dpv-body");
    box.appendChild(head); box.appendChild(body); ov.appendChild(box);
    document.body.appendChild(ov);
    document.body.classList.add("dpv-lock");
    function close() { ov.remove(); document.body.classList.remove("dpv-lock"); document.removeEventListener("keydown", esc); }
    function esc(e) { if (e.key === "Escape") close(); }
    x.addEventListener("click", close);
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    document.addEventListener("keydown", esc);
    Viewer(body, url, true);
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-dp-open]");
    if (!b) return;
    e.preventDefault();
    openModal(b.getAttribute("data-dp-open"), b.getAttribute("data-dp-title"));
  });
  function boot() {
    document.querySelectorAll("[data-dp-inline]").forEach(function (h) {
      if (h.dataset.dpDone) return;
      h.dataset.dpDone = "1";
      Viewer(h, h.getAttribute("data-dp-inline"), window.matchMedia("(min-width: 700px)").matches);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();

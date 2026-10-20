/* Applied before styles load; storage can be unavailable in managed browsers. */
"use strict";
const theme = (() => {
  const key = "opstrail.theme";
  const media = matchMedia("(prefers-color-scheme: dark)");
  const valid = (value) => ["auto", "light", "dark"].includes(value) ? value : "auto";
  let preference = "auto";
  try { preference = valid(localStorage.getItem(key)); } catch { /* Use OS preference. */ }
  const sync = () => {
    document.documentElement.dataset.theme = preference === "auto" ? (media.matches ? "dark" : "light") : preference;
    document.querySelectorAll("[data-theme-select]").forEach((el) => { el.value = preference; });
  };
  const set = (value) => {
    preference = valid(value);
    try { localStorage.setItem(key, preference); } catch { /* Current tab still works. */ }
    sync();
  };
  media.addEventListener("change", sync);
  window.addEventListener("storage", (e) => {
    if (e.key === key || e.key === null) { preference = valid(e.newValue); sync(); }
  });
  sync();
  return { set, sync };
})();

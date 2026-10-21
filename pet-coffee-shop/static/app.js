const $ = (s) => document.querySelector(s);
const peso = (n) => "₱" + Number(n).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function toast(text) {
  const el = $("#toast"); el.textContent = text; el.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("show"), 2500);
}
async function api(path, body, method = "POST") {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (res.status === 401) location.href = "/";
  return res.json();
}
const openModal  = () => $("#modal").classList.add("open");
const closeModal = () => $("#modal").classList.remove("open");
async function submitForm(event, path) {
  event.preventDefault();
  const result = await api(path, Object.fromEntries(new FormData(event.target)));
  result.ok ? location.reload() : toast(result.error);
}
async function setStatus(id, status) {
  const result = await api(`/api/appointments/${id}/status`, { status });
  result.ok ? location.reload() : toast(result.error);
}
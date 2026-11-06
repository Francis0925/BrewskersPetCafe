const $ = (selector) => document.querySelector(selector);

const peso = (amount) =>
  "₱" +
  Number(amount).toLocaleString("en-PH", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });

function toast(text, type = "success") {
  const element = $("#toast");

  if (!element) return;

  element.innerHTML =
    '<span class="toast-ic">' +
    (type === "error" ? "!" : type === "info" ? "i" : "✓") +
    '</span><span class="toast-text"></span>';

  element.querySelector(".toast-text").textContent = text;
  element.className = `toast ${type} show`;

  clearTimeout(toast.timer);

  toast.timer = setTimeout(
    () => element.classList.remove("show"),
    type === "error" ? 4000 : 2500
  );
}

function csrfToken() {
  return (
    document.querySelector('meta[name="csrf-token"]')?.content ||
    window.CSRF_TOKEN ||
    ""
  );
}

async function api(path, body = {}, method = "POST") {
  const options = {
    method,
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json"
    }
  };

  if (!["GET", "HEAD"].includes(method.toUpperCase())) {
    const token = csrfToken();

    if (token) {
      options.headers["X-CSRF-Token"] = token;
    }

    options.body = JSON.stringify(body || {});
  }

  let response;

  try {
    response = await fetch(path, options);
  } catch (error) {
    return {
      ok: false,
      error: "Could not reach the server"
    };
  }

  if (response.status === 401) {
    location.href = "/";

    return {
      ok: false,
      error: "Please log in"
    };
  }

  let result;

  try {
    result = await response.json();
  } catch (error) {
    result = {
      ok: false,
      error: "The server returned an invalid response"
    };
  }

  if (response.status === 403) {
    return {
      ok: false,
      error: (
        result.error ||
        "Your session expired. Refresh the page and try again."
      )
    };
  }

  if (response.status === 429) {
    return {
      ok: false,
      error: "Too many attempts. Please wait and try again."
    };
  }

  if (!response.ok && result.ok === undefined) {
    result.ok = false;
    result.error = (
      result.error ||
      "The request could not be completed."
    );
  }

  return result;
}

const openModal = () => $("#modal")?.classList.add("open");
const closeModal = () => $("#modal")?.classList.remove("open");

async function submitForm(event, path) {
  event.preventDefault();

  const result = await api(
    path,
    Object.fromEntries(new FormData(event.target))
  );

  if (result.ok) {
    location.reload();
  } else {
    toast(result.error || "Could not save", "error");
  }
}

async function setStatus(id, status) {
  const result = await api(
    `/api/appointments/${id}/status`,
    { status }
  );

  if (result.ok) {
    location.reload();
  } else {
    toast(
      result.error || "Could not update appointment",
      "error"
    );
  }
}
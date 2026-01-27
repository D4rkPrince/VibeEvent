const apiStatus = document.getElementById("apiStatus");
const documentsGrid = document.getElementById("documentsGrid");
const emptyState = document.getElementById("emptyState");
const refreshButton = document.getElementById("refreshButton");
const searchInput = document.getElementById("searchInput");
const reminderButton = document.getElementById("reminderButton");
const clearAllButton = document.getElementById("clearAllButton");
const openAddModalButton = document.getElementById("openAddModal");
const addModal = document.getElementById("addModal");
const addForm = document.getElementById("addForm");
const addMessage = document.getElementById("addMessage");
const historyModal = document.getElementById("historyModal");
const historyList = document.getElementById("historyList");
const toast = document.getElementById("toast");
const statExpired = document.getElementById("statExpired");
const statSoon = document.getElementById("statSoon");
const statMid = document.getElementById("statMid");
const statActive = document.getElementById("statActive");

let documents = [];
let currentFilter = "all";

const formatShortDate = (value) => {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("ru-RU");
};

const formatLongDate = (value) => {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
};

const escapeHtml = (text) =>
  String(text || "").replace(/[&<>"']/g, (match) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[match]));

const isValidDateValue = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(value);
  return (
    date.getFullYear() === year &&
    date.getMonth() + 1 === month &&
    date.getDate() === day
  );
};

const getDaysToExpiry = (expiryDate) => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(expiryDate);
  target.setHours(0, 0, 0, 0);
  const diff = target - today;
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
};

const getStatus = (doc) => {
  const days = getDaysToExpiry(doc.expiry_date);
  if (days < 0) return { key: "expired", label: "Истек" };
  if (days <= 30) return { key: "soon", label: "Скоро" };
  if (days <= 60) return { key: "mid", label: "30–60 дней" };
  return { key: "active", label: "Активен" };
};

const showToast = (message) => {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 3000);
};

const setActiveFilter = (filterKey) => {
  currentFilter = filterKey;
  document.querySelectorAll(".stat-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.filter === filterKey);
  });
  renderDocuments();
};

const updateStats = () => {
  let expired = 0;
  let soon = 0;
  let mid = 0;
  let active = 0;
  documents.forEach((doc) => {
    const status = getStatus(doc).key;
    if (status === "expired") expired += 1;
    if (status === "soon") soon += 1;
    if (status === "mid") mid += 1;
    if (status === "active") active += 1;
  });
  statExpired.textContent = expired;
  statSoon.textContent = soon;
  statMid.textContent = mid;
  statActive.textContent = active;
};

const renderDocuments = () => {
  const term = searchInput.value.trim().toLowerCase();
  const filtered = documents.filter((doc) => {
    const status = getStatus(doc).key;
    const matchesFilter = currentFilter === "all" || status === currentFilter;
    const matchesSearch =
      !term ||
      doc.title.toLowerCase().includes(term) ||
      doc.doc_type.toLowerCase().includes(term);
    return matchesFilter && matchesSearch;
  });

  if (!filtered.length) {
    documentsGrid.innerHTML = "";
    emptyState.style.display = "block";
    return;
  }

  emptyState.style.display = "none";
  documentsGrid.innerHTML = filtered
    .map((doc) => {
      const status = getStatus(doc);
      return `
        <article class="doc-card ${status.key}">
          <div class="doc-header">
            <div class="doc-title">
              <strong>${escapeHtml(doc.title)}</strong>
              <span class="doc-meta">${escapeHtml(doc.doc_type)}</span>
              <span class="doc-meta">№ ${doc.id}</span>
            </div>
            <span class="doc-tag ${status.key}">${status.label}</span>
          </div>
          <div class="doc-date">до ${formatLongDate(doc.expiry_date)}</div>
          <div class="doc-actions">
            <div class="row">
              <input type="date" data-renew="${doc.id}" />
              <button class="ghost" data-renew-button="${doc.id}">Продлить</button>
              <button class="ghost" data-history-button="${doc.id}">История</button>
              <button class="danger" data-delete-button="${doc.id}">Удалить</button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
};

const renderHistory = (items) => {
  if (!items.length) {
    historyList.textContent = "История пуста";
    return;
  }
  historyList.innerHTML = items
    .map(
      (item) => `
        <div class="history-item">
          <strong>Документ #${item.document_id}</strong>
          <div>${formatShortDate(item.old_expiry_date)} → ${formatShortDate(
        item.new_expiry_date
      )}</div>
          <div class="doc-meta">Обновлено: ${new Date(
            item.updated_at
          ).toLocaleString("ru-RU")}</div>
        </div>
      `
    )
    .join("");
};

const fetchJson = async (url, options) => {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Ошибка запроса");
  }
  return payload;
};

const checkHealth = async () => {
  try {
    await fetchJson("/health");
    apiStatus.textContent = "API: доступно";
    apiStatus.style.background = "#dcfce7";
    apiStatus.style.color = "#166534";
  } catch (error) {
    apiStatus.textContent = "API: недоступно";
    apiStatus.style.background = "#fee2e2";
    apiStatus.style.color = "#991b1b";
  }
};

const loadDocuments = async () => {
  documentsGrid.innerHTML = "";
  emptyState.textContent = "Загрузка...";
  emptyState.style.display = "block";
  try {
    const data = await fetchJson("/documents");
    documents = data;
    updateStats();
    renderDocuments();
  } catch (error) {
    emptyState.textContent = `Ошибка: ${error.message}`;
  }
};

const sendReminder = async () => {
  try {
    const data = await fetchJson("/reminders/send?days=30&mode=email", {
      method: "POST",
    });
    showToast(`Отправлено: ${data.sent}. Адрес: ${data.target}`);
  } catch (error) {
    showToast(`Ошибка: ${error.message}`);
  }
};

const deleteDocument = async (documentId) => {
  try {
    await fetchJson(`/documents/${documentId}`, { method: "DELETE" });
    return { alreadyDeleted: false };
  } catch (error) {
    const message = String(error.message || "");
    if (message.includes("Not Found") || message.includes("Документ не найден")) {
      try {
        await fetchJson(`/documents/${documentId}/delete`, { method: "POST" });
        return { alreadyDeleted: false };
      } catch (fallbackError) {
        const fallbackMessage = String(fallbackError.message || "");
        if (
          fallbackMessage.includes("Not Found") ||
          fallbackMessage.includes("Документ не найден")
        ) {
          return { alreadyDeleted: true };
        }
        throw fallbackError;
      }
    }
    throw error;
  }
};

const clearAllDocuments = async () => {
  return fetchJson("/documents/clear", { method: "POST" });
};

const renewDocument = async (documentId, newExpiry) => {
  if (!newExpiry) {
    throw new Error("Укажите новую дату окончания");
  }
  if (!isValidDateValue(newExpiry)) {
    throw new Error("Некорректная дата");
  }
  await fetchJson(`/documents/${documentId}/renew`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_expiry_date: newExpiry }),
  });
};

const openModal = (modal) => {
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
};

const closeModal = (modal) => {
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
};

openAddModalButton.addEventListener("click", () => {
  addMessage.textContent = "";
  addForm.reset();
  openModal(addModal);
});

document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = document.getElementById(button.dataset.close);
    if (target) closeModal(target);
  });
});

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  addMessage.textContent = "Сохраняем...";
  const formData = new FormData(addForm);
  const payload = Object.fromEntries(formData.entries());
  if (!isValidDateValue(payload.expiry_date)) {
    addMessage.textContent = "Некорректная дата";
    return;
  }
  try {
    await fetchJson("/documents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    addMessage.textContent = "Документ добавлен";
    await loadDocuments();
    setTimeout(() => closeModal(addModal), 500);
  } catch (error) {
    addMessage.textContent = `Ошибка: ${error.message}`;
  }
});

documentsGrid.addEventListener("click", async (event) => {
  const target = event.target;
  if (target.matches("[data-renew-button]")) {
    const documentId = target.getAttribute("data-renew-button");
    const input = documentsGrid.querySelector(`input[data-renew="${documentId}"]`);
    try {
      await renewDocument(documentId, input.value);
      await loadDocuments();
      showToast("Документ обновлен");
    } catch (error) {
      showToast(`Ошибка: ${error.message}`);
    }
  }

  if (target.matches("[data-delete-button]")) {
    const documentId = target.getAttribute("data-delete-button");
    if (!confirm("Удалить документ?")) return;
    try {
      const result = await deleteDocument(documentId);
      await loadDocuments();
      showToast(result.alreadyDeleted ? "Документ уже удален" : "Документ удален");
    } catch (error) {
      await loadDocuments();
      showToast(`Ошибка: ${error.message}`);
    }
  }

  if (target.matches("[data-history-button]")) {
    const documentId = target.getAttribute("data-history-button");
    historyList.textContent = "Загрузка...";
    try {
      const data = await fetchJson(`/documents/${documentId}/history`);
      renderHistory(data);
      openModal(historyModal);
    } catch (error) {
      historyList.textContent = `Ошибка: ${error.message}`;
      openModal(historyModal);
    }
  }
});

document.querySelectorAll(".stat-card").forEach((card) => {
  card.addEventListener("click", () => setActiveFilter(card.dataset.filter));
});

refreshButton.addEventListener("click", loadDocuments);
searchInput.addEventListener("input", renderDocuments);
reminderButton.addEventListener("click", sendReminder);
clearAllButton.addEventListener("click", async () => {
  if (!confirm("Удалить все документы?")) return;
  try {
    const result = await clearAllDocuments();
    await loadDocuments();
    showToast(`Удалено документов: ${result.deleted}`);
  } catch (error) {
    showToast(`Ошибка: ${error.message}`);
  }
});

checkHealth();
loadDocuments();

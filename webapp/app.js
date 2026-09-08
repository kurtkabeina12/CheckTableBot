const tg = window.Telegram?.WebApp;

if (tg) {
  tg.ready();
  tg.expand();

  if (tg.themeParams?.bg_color) {
    document.documentElement.style.setProperty(
      "--tg-bg",
      tg.themeParams.bg_color
    );
  }
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const WEEKDAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

const state = {
  accounts: [],
  employees: [],
  vacations: [],

  // Только frontend/localStorage
  demandTemplates: JSON.parse(
    localStorage.getItem("demandTemplates") || "[]"
  ),

  demandOverrides: JSON.parse(
    localStorage.getItem("demandOverrides") || "[]"
  ),

  bookings: JSON.parse(
    localStorage.getItem("bookings") || "[]"
  ),

  schedule: null,
  selectedDay: null,
  editingEmpId: null,

  bookingUserName:
    localStorage.getItem("bookingUserName") || "",
};


/* =========================================================
   API
========================================================= */

async function api(path, options = {}) {
  const initData =
    tg?.initData || "";

  const res = await fetch(path, {
    ...options,

    headers: {
      "Content-Type": "application/json",

      ...(initData
        ? {
            "X-Telegram-Init-Data":
              initData,
          }
        : {}),

      ...(options.headers || {}),
    },
  });

  if (!res.ok) {
    let msg = res.statusText;

    try {
      const data = await res.json();

      msg =
        data.detail ||
        JSON.stringify(data);

    } catch (_) {}

    throw new Error(
      typeof msg === "string"
        ? msg
        : JSON.stringify(msg)
    );
  }

  if (res.status === 204) {
    return null;
  }

  return res.json();
}


/* =========================================================
   HELPERS
========================================================= */

function toast(msg, isError = false) {
  if (tg?.showAlert) {
    tg.showAlert(msg);
    return;
  }

  alert(msg);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtDate(iso) {
  if (!iso) return "";

  const [y, m, d] = iso.split("-");

  return `${d}.${m}.${y}`;
}

function saveLocalState() {
  localStorage.setItem(
    "demandTemplates",
    JSON.stringify(state.demandTemplates)
  );

  localStorage.setItem(
    "demandOverrides",
    JSON.stringify(state.demandOverrides)
  );

  localStorage.setItem(
    "bookings",
    JSON.stringify(state.bookings)
  );
}


/* =========================================================
   TABS
========================================================= */

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchTab(btn.dataset.tab);
  });
});

function switchTab(tabName) {
  $$(".tab").forEach((b) => {
    b.classList.toggle(
      "active",
      b.dataset.tab === tabName
    );
  });

  $$(".panel").forEach((p) => {
    p.classList.toggle(
      "active",
      p.id === `panel-${tabName}`
    );
  });
}


/* =========================================================
   PEOPLE / ACCOUNTS
========================================================= */

function patternLabel(emp) {
  const t = emp.schedule_type;

  if (t === "2/2" || t === "3/3") {
    const time =
      emp.time_start || emp.time_end
        ? ` · ${emp.time_start || "?"}${emp.time_end ? "–" + emp.time_end : ""
        }`
        : "";

    return `${t} с ${emp.cycle_start || "?"}${time}`;
  }

  if (t === "weekdays") {
    if (emp.day_slots?.length) {
      return emp.day_slots
        .map((s) => {
          const time =
            s.time_start || s.time_end
              ? ` ${s.time_start || "?"}${s.time_end ? "–" + s.time_end : ""
              }`
              : "";

          return `${WEEKDAY_NAMES[s.weekday]}${time}`;
        })
        .join(", ");
    }

    return `дни: ${(emp.weekdays || [])
      .map((d) => WEEKDAY_NAMES[d])
      .join(", ")}`;
  }

  if (t === "5/2") {
    const time =
      emp.time_start || emp.time_end
        ? ` · ${emp.time_start || "?"}${emp.time_end ? "–" + emp.time_end : ""
        }`
        : "";

    return `5/2 (пн–пт)${time}`;
  }

  return t || "График не настроен";
}


function slotOptions(selected) {
  return WEEKDAY_NAMES.map(
    (name, idx) =>
      `<option value="${idx}" ${Number(selected) === idx ? "selected" : ""
      }>${name}</option>`
  ).join("");
}


function renderDaySlots(slots = []) {
  const list = $("#day-slots");

  const rows = slots.length
    ? slots
    : [
      {
        weekday: 1,
        time_start: "12:00",
        time_end: "01:00",
      },
    ];

  list.innerHTML = rows
    .map(
      (slot, idx) => `
        <div class="slot-row" data-slot-idx="${idx}">
          <label>
            День
            <select data-slot-weekday>
              ${slotOptions(slot.weekday ?? 1)}
            </select>
          </label>

          <label>
            С
            <input
              type="time"
              data-slot-start
              value="${slot.time_start || ""}"
            />
          </label>

          <label>
            По
            <input
              type="time"
              data-slot-end
              value="${slot.time_end || ""}"
            />
          </label>

          <button
            type="button"
            class="btn danger"
            data-remove-slot
          >
            ✕
          </button>
        </div>
      `
    )
    .join("");
}


function collectDaySlots() {
  return $$("#day-slots .slot-row").map((row) => ({
    weekday: Number(
      row.querySelector("[data-slot-weekday]").value
    ),

    time_start:
      row.querySelector("[data-slot-start]").value || "",

    time_end:
      row.querySelector("[data-slot-end]").value || "",
  }));
}


function toggleTypeFields() {
  const type = $("#emp-type").value;

  const cycle =
    type === "2/2" ||
    type === "3/3";

  const weekdays =
    type === "weekdays";

  $("#cycle-fields").classList.toggle(
    "hidden",
    !cycle
  );

  $("#weekday-fields").classList.toggle(
    "hidden",
    !weekdays
  );

  $("#default-time-fields").classList.toggle(
    "hidden",
    weekdays
  );

  $("#default-time-hint").classList.toggle(
    "hidden",
    weekdays
  );

  $("#emp-cycle-start").required = cycle;
}


/* =========================================================
   ACCOUNT LIST
========================================================= */

async function loadAccounts() {
  state.accounts = await api("/api/accounts");

  renderEmployees();
  fillVacEmpSelect();
}


function renderEmployees() {
  const list = $("#emp-list");

  if (!state.accounts.length) {
    list.innerHTML = `
      <li class="empty">
        В таблице accounts пока нет сотрудников
      </li>
    `;

    return;
  }

  list.innerHTML = state.accounts
    .map((account) => {
      const configured = Boolean(account.configured);

      const badge = configured
        ? `<span class="badge">Настроено</span>`
        : `<span class="badge">Не настроено</span>`;

      const description = configured
        ? patternLabel(account)
        : "График ещё не настроен";

      return `
        <li class="card">
          <div>
            <h4>
              ${escapeHtml(account.name || account.username)}
              ${badge}
            </h4>

            <div class="meta">
              ${escapeHtml(description)}
              ${account.note
          ? " · " + escapeHtml(account.note)
          : ""
        }
            </div>
          </div>

          <div class="card-actions">
            <button
              type="button"
              class="btn primary"
              data-configure-account="${account.id}"
            >
              ${configured ? "Настроить" : "Настроить график"}
            </button>

            ${configured
          ? `
                  <button
                    type="button"
                    class="btn danger"
                    data-del-emp="${account.id}"
                  >
                    Сбросить
                  </button>
                `
          : ""
        }
          </div>
        </li>
      `;
    })
    .join("");
}


/* =========================================================
   EMPLOYEE MODAL
========================================================= */

function openEmpModal(account) {
  state.editingEmpId = account.id;

  $("#emp-modal-title").textContent =
    account.configured
      ? "Настройка графика"
      : "Настроить график";

  $("#emp-id").value = account.id;

  // Имя теперь только для отображения.
  // Редактировать имя accounts здесь нельзя.
  $("#emp-name").value =
    account.name || account.username || "";

  $("#emp-name").readOnly = true;

  $("#emp-type").value =
    account.schedule_type || "3/3";

  $("#emp-cycle-start").value =
    account.cycle_start || "";

  $("#emp-time-start").value =
    account.time_start || "";

  $("#emp-time-end").value =
    account.time_end || "";

  $("#emp-note").value =
    account.note || "";

  const slots =
    account.day_slots?.length
      ? account.day_slots
      : (account.weekdays || []).map((d) => ({
        weekday: d,
        time_start: account.time_start || "",
        time_end: account.time_end || "",
      }));

  renderDaySlots(slots);

  toggleTypeFields();

  $("#emp-modal").showModal();
}


$("#emp-type").addEventListener(
  "change",
  toggleTypeFields
);


$("#emp-cancel").addEventListener(
  "click",
  () => $("#emp-modal").close()
);


$("#btn-add-slot").addEventListener(
  "click",
  () => {
    const slots = collectDaySlots();

    slots.push({
      weekday: 4,
      time_start: "20:00",
      time_end: "01:00",
    });

    renderDaySlots(slots);
  }
);


$("#day-slots").addEventListener(
  "click",
  (ev) => {
    const btn =
      ev.target.closest("[data-remove-slot]");

    if (!btn) return;

    const slots = collectDaySlots();

    const idx = Number(
      btn.closest(".slot-row").dataset.slotIdx
    );

    slots.splice(idx, 1);

    renderDaySlots(slots);
  }
);


$("#emp-form").addEventListener(
  "submit",
  async (ev) => {
    ev.preventDefault();

    const accountId =
      Number($("#emp-id").value);

    const type =
      $("#emp-type").value;

    const day_slots =
      type === "weekdays"
        ? collectDaySlots()
        : [];

    const weekdays =
      day_slots.map((s) => s.weekday);

    const body = {
      account_id: accountId,

      schedule_type: type,

      cycle_start:
        $("#emp-cycle-start").value || null,

      weekdays,

      day_slots,

      time_start:
        $("#emp-time-start").value || "",

      time_end:
        $("#emp-time-end").value || "",

      note:
        $("#emp-note").value.trim(),

      active: true,
    };

    try {
      await api("/api/employees", {
        method: "POST",
        body: JSON.stringify(body),
      });

      $("#emp-modal").close();

      await loadAccounts();

      toast("График сохранён");

      await rebuildAndShowSchedule();

    } catch (e) {
      toast(e.message, true);
    }
  }
);


/* =========================================================
   PEOPLE EVENTS
========================================================= */

$("#emp-list").addEventListener(
  "click",
  async (ev) => {
    const configure =
      ev.target.closest(
        "[data-configure-account]"
      );

    const deleteBtn =
      ev.target.closest(
        "[data-del-emp]"
      );

    if (configure) {
      const id =
        Number(configure.dataset.configureAccount);

      const account =
        state.accounts.find(
          (a) => Number(a.id) === id
        );

      if (account) {
        openEmpModal(account);
      }

      return;
    }

    if (deleteBtn) {
      const id =
        Number(deleteBtn.dataset.delEmp);

      const account =
        state.accounts.find(
          (a) => Number(a.id) === id
        );

      if (!account) return;


      const confirmed = await showConfirmModal({
        title: "Сбросить график?",
        text: "График сотрудника будет удалён, но сам аккаунт останется в системе.",
        confirmText: "Сбросить",
      });

      if (!confirmed) {
        return;
      }


      try {
        await api(`/api/employees/${id}`, {
          method: "DELETE",
        });

        await loadAccounts();
        await loadVacations();

        if (state.schedule) {
          await reloadCurrentSchedule(false);
        }

      } catch (e) {
        toast(e.message, true);
      }
    }
  }
);


$("#btn-refresh-accounts").addEventListener(
  "click",
  async () => {
    try {
      await loadAccounts();
      toast("Список обновлён");
    } catch (e) {
      toast(e.message, true);
    }
  }
);


/* =========================================================
   VACATIONS
========================================================= */

function fillVacEmpSelect() {
  const sel = $("#vac-emp");

  const configured =
    state.accounts.filter(
      (a) => a.configured
    );

  sel.innerHTML = configured
    .map(
      (e) =>
        `<option value="${e.id}">
          ${escapeHtml(e.name || e.username)}
        </option>`
    )
    .join("");
}


async function loadVacations() {
  state.vacations =
    await api("/api/vacations");

  renderVacations();
}


function renderVacations() {
  const list = $("#vac-list");

  if (!state.vacations.length) {
    list.innerHTML = `
      <li class="empty">
        Отпусков пока нет
      </li>
    `;

    return;
  }

  list.innerHTML =
    state.vacations
      .map(
        (v) => `
          <li class="card">
            <div>
              <h4>
                ${escapeHtml(v.emp_name)}
              </h4>

              <div class="meta">
                ${fmtDate(v.start_date)}
                —
                ${fmtDate(v.end_date)}
                ${v.comment
            ? " · " +
            escapeHtml(v.comment)
            : ""
          }
              </div>
            </div>

            <div class="card-actions">
              <button
                type="button"
                class="btn danger"
                data-del-vac="${v.id}"
              >
                🗑
              </button>
            </div>
          </li>
        `
      )
      .join("");
}


$("#btn-add-vac").addEventListener(
  "click",
  () => {
    const configured =
      state.accounts.filter(
        (a) => a.configured
      );

    if (!configured.length) {
      toast(
        "Сначала настройте график хотя бы одному сотруднику"
      );

      return;
    }

    fillVacEmpSelect();

    $("#vac-start").value = "";
    $("#vac-end").value = "";
    $("#vac-comment").value = "";

    $("#vac-modal").showModal();
  }
);


$("#vac-cancel").addEventListener(
  "click",
  () => $("#vac-modal").close()
);


$("#vac-form").addEventListener(
  "submit",
  async (ev) => {
    ev.preventDefault();

    try {
      await api("/api/vacations", {
        method: "POST",

        body: JSON.stringify({
          emp_id:
            Number($("#vac-emp").value),

          start_date:
            $("#vac-start").value,

          end_date:
            $("#vac-end").value,

          comment:
            $("#vac-comment").value.trim(),
        }),
      });

      $("#vac-modal").close();

      await loadVacations();

      await rebuildAndShowSchedule();

    } catch (e) {
      toast(e.message, true);
    }
  }
);


$("#vac-list").addEventListener(
  "click",
  async (ev) => {
    const btn =
      ev.target.closest(
        "[data-del-vac]"
      );

    if (!btn) return;

    const id = btn.dataset.delVac;

const confirmed = await showConfirmModal({
  title: "Удалить отпуск?",
  text: "Запись об отпуске будет удалена.",
  confirmText: "Удалить",
});

if (!confirmed) {
  return;
}

    try {
      await api(`/api/vacations/${id}`, {
        method: "DELETE",
      });

      await loadVacations();

      await rebuildAndShowSchedule();

    } catch (e) {
      toast(e.message, true);
    }
  }
);


/* =========================================================
   DEMAND — LOCALSTORAGE ONLY
========================================================= */

function renderDemandTemplates() {
  const grid =
    $("#demand-template-grid");

  grid.innerHTML =
    WEEKDAY_NAMES
      .map((name, weekday) => {
        const row =
          state.demandTemplates.find(
            (item) =>
              Number(item.weekday) === weekday
          ) || {
            weekday,
            required_people: 0,
          };

        return `
          <div class="template-item">
            <strong>${name}</strong>

            <label>
              Нужно людей

              <input
                type="number"
                min="0"
                data-template-weekday="${weekday}"
                value="${Number(
          row.required_people || 0
        )}"
              />
            </label>
          </div>
        `;
      })
      .join("");
}


function renderDemandOverrides() {
  const list =
    $("#override-list");

  if (!state.demandOverrides.length) {
    list.innerHTML = `
      <li class="empty">
        Исключений по датам пока нет
      </li>
    `;

    return;
  }

  list.innerHTML =
    state.demandOverrides
      .map(
        (item) => `
          <li class="card">
            <div>
              <h4>
                ${fmtDate(item.date)}

                <span class="badge">
                  ${item.required_people} чел.
                </span>
              </h4>

              <div class="meta">
                ${item.comment
            ? escapeHtml(item.comment)
            : "Без комментария"
          }
              </div>
            </div>

            <div class="card-actions">
              <button
                type="button"
                class="btn danger"
                data-del-override="${item.id}"
              >
                🗑
              </button>
            </div>
          </li>
        `
      )
      .join("");
}


function loadDemand() {
  renderDemandTemplates();
  renderDemandOverrides();
}


$("#btn-save-template").addEventListener(
  "click",
  async () => {
    const inputs =
      $$("[data-template-weekday]");

    state.demandTemplates =
      inputs.map((input) => ({
        weekday:
          Number(
            input.dataset.templateWeekday
          ),

        required_people:
          Number(input.value || 0),
      }));

    saveLocalState();

    toast(
      "Шаблон потребности сохранён на этом устройстве"
    );

    await refreshScheduleIfLoaded();
  }
);


$("#btn-add-override").addEventListener(
  "click",
  () => {
    $("#override-date").value = "";
    $("#override-required").value = "0";
    $("#override-comment").value = "";

    $("#override-modal").showModal();
  }
);


$("#override-cancel").addEventListener(
  "click",
  () => $("#override-modal").close()
);


$("#override-form").addEventListener(
  "submit",
  async (ev) => {
    ev.preventDefault();

    const item = {
      id:
        `${Date.now()}-${Math.random()
          .toString(36)
          .slice(2)}`,

      date:
        $("#override-date").value,

      required_people:
        Number(
          $("#override-required").value || 0
        ),

      comment:
        $("#override-comment").value.trim(),
    };

    state.demandOverrides.push(item);

    state.demandOverrides.sort(
      (a, b) =>
        a.date.localeCompare(b.date)
    );

    saveLocalState();

    $("#override-modal").close();

    renderDemandOverrides();

    await refreshScheduleIfLoaded();
  }
);


$("#override-list").addEventListener(
  "click",
  async (ev) => {
    const btn = ev.target.closest("[data-del-override]");

    if (!btn) return;

    const id = btn.dataset.delOverride;

    const confirmed = await showConfirmModal({
      title: "Удалить исключение?",
      text: "Настройка потребности для этой даты будет удалена.",
      confirmText: "Удалить",
    });

    if (!confirmed) {
      return;
    }

    state.demandOverrides =
      state.demandOverrides.filter(
        (item) =>
          String(item.id) !== String(id)
      );

    saveLocalState();

    renderDemandOverrides();

    await refreshScheduleIfLoaded();
  }
);


/* =========================================================
   BOOKINGS — LOCALSTORAGE ONLY
========================================================= */

function getBookingUserName() {
  const current =
    state.bookingUserName || "";

  const input = prompt(
    "Кто бронирует? Введите имя",
    current
  );

  if (!input) return "";

  const name = input.trim();

  if (!name) return "";

  state.bookingUserName = name;

  localStorage.setItem(
    "bookingUserName",
    name
  );

  return name;
}


function statusClass(status) {
  return status === "booked"
    ? "booking-booked"
    : status === "closed"
      ? "booking-closed"
      : "booking-needed";
}


function statusLabel(status) {
  return status === "booked"
    ? "Забронировано"
    : status === "closed"
      ? "Закрыто"
      : "Нужно бронировать";
}


function renderBookings() {
  const list =
    $("#booking-list");

  const items =
    [...state.bookings]
      .filter(
        (item) =>
          Number(item.shortage) > 0
      )
      .sort(
        (a, b) =>
          a.date.localeCompare(b.date)
      );

  if (!items.length) {
    list.innerHTML = `
      <li class="empty">
        Сейчас везде достаточно людей —
        бронировать нечего
      </li>
    `;

    return;
  }

  list.innerHTML =
    items
      .map(
        (item) => `
          <li class="card">
            <div>
              <h4>
                ${fmtDate(item.date)}

                <span
                  class="booking-status ${statusClass(
          item.status
        )}"
                >
                  ${statusLabel(
          item.status
        )}
                </span>
              </h4>

              <div class="meta">
                Нужно:
                ${item.required_people}

                · Есть:
                ${item.available_people}

                ·
                <span class="shortage">
                  Мало на ${item.shortage}
                </span>
              </div>

              <div class="meta">
                ${item.booked_by
            ? `Забронировал(а):
                       ${escapeHtml(
              item.booked_by
            )}`
            : "Можно отметить, когда место забронировали"
          }
              </div>

              ${item.comment
            ? `
                    <div class="meta">
                      ${escapeHtml(
              item.comment
            )}
                    </div>
                  `
            : ""
          }
            </div>

            <div class="card-actions">
              <button
                type="button"
                class="btn primary"
                data-booking-status="${item.id}"
                data-status="booked"
              >
                Бронь
              </button>

              <button
                type="button"
                class="btn"
                data-booking-status="${item.id}"
                data-status="closed"
              >
                Закрыто
              </button>

              <button
                type="button"
                class="btn danger"
                data-booking-status="${item.id}"
                data-status="needed"
              >
                Сброс
              </button>
            </div>
          </li>
        `
      )
      .join("");
}


function updateBooking(
  bookingId,
  status,
  bookedBy = ""
) {
  const item =
    state.bookings.find(
      (b) =>
        String(b.id) ===
        String(bookingId)
    );

  if (!item) return;

  item.status = status;
  item.booked_by = bookedBy;

  saveLocalState();

  renderBookings();
}


$("#booking-list").addEventListener(
  "click",
  (ev) => {
    const button =
      ev.target.closest(
        "[data-booking-status]"
      );

    if (!button) return;

    const id =
      button.dataset.bookingStatus;

    const status =
      button.dataset.status;

    const bookedBy =
      status === "booked"
        ? getBookingUserName()
        : "";

    if (
      status === "booked" &&
      !bookedBy
    ) {
      toast(
        "Имя не указано, бронь не поставлена"
      );

      return;
    }

    updateBooking(
      id,
      status,
      bookedBy
    );

    if (state.selectedDay) {
      openDayView(
        state.selectedDay
      );
    }
  }
);


/* =========================================================
   SCHEDULE
========================================================= */

function setMonthPicker(
  year,
  month
) {
  $("#month-picker").value =
    `${year}-${String(month).padStart(
      2,
      "0"
    )}`;
}


function parseTimeMinutes(value) {
  if (!value) return null;

  const match =
    String(value)
      .trim()
      .match(
        /^(\d{1,2}):(\d{2})$/
      );

  if (!match) return null;

  return (
    Number(match[1]) * 60 +
    Number(match[2])
  );
}


function splitTimeRange(label) {
  if (!label) {
    return {
      start: "",
      end: "",
      startMin: null,
      endMin: null,
    };
  }

  const parts =
    String(label)
      .split(/[–-]/)
      .map((x) => x.trim());

  const start = parts[0] || "";
  const end = parts[1] || "";

  let startMin =
    parseTimeMinutes(start);

  let endMin =
    parseTimeMinutes(end);

  if (
    startMin != null &&
    endMin != null &&
    endMin <= startMin
  ) {
    endMin += 24 * 60;
  }

  return {
    start,
    end,
    startMin,
    endMin,
  };
}


function peopleForDay(dateIso) {
  if (!state.schedule) return [];

  const result = [];

  for (
    const person
    of state.schedule.people || []
  ) {
    const cell =
      (person.cells || []).find(
        (c) => c.date === dateIso
      );

    if (
      !cell ||
      cell.status !== "work"
    ) {
      continue;
    }

    const range =
      splitTimeRange(
        cell.time ||
        person.time_label ||
        ""
      );

    result.push({
      name: person.name,

      time:
        cell.time ||
        person.time_label ||
        "",

      start: range.start,

      end: range.end,

      startMin:
        range.startMin ??
        24 * 60,

      endMin:
        range.endMin ??
        range.startMin ??
        24 * 60,
    });
  }

  result.sort(
    (a, b) =>
      a.startMin - b.startMin ||
      a.name.localeCompare(
        b.name,
        "ru"
      )
  );

  return result;
}


function buildHourTable(people) {
  const rows = [];

  for (
    let hour = 0;
    hour < 24;
    hour++
  ) {
    const start =
      hour * 60;

    const end =
      (hour + 1) * 60;

    const active =
      people
        .filter((p) => {
          const s =
            p.startMin ??
            24 * 60;

          const e =
            p.endMin ?? s;

          return (
            s < end &&
            e > start
          );
        })
        .map(
          (p) =>
            `${p.name}${p.time
              ? ` (${p.time})`
              : ""
            }`
        );

    const hourLabel =
      `${String(hour).padStart(
        2,
        "0"
      )}:00–${String(
        (hour + 1) % 24
      ).padStart(
        2,
        "0"
      )}:00`;

    rows.push(`
      <tr>
        <th>${hourLabel}</th>
        <td>
          ${active.length
        ? active
          .map(escapeHtml)
          .join(", ")
        : `<span class="hour-empty">—</span>`
      }
        </td>
      </tr>
    `);
  }

  return `
    <table class="day-hours">
      <tbody>
        ${rows.join("")}
      </tbody>
    </table>
  `;
}


function showDaysView() {
  $("#days-view")
    .classList
    .remove("hidden");

  $("#day-view")
    .classList
    .add("hidden");

  state.selectedDay = null;

  $$(".month-day")
    .forEach((el) =>
      el.classList.remove(
        "selected"
      )
    );
}


/* =========================================================
   LOCAL BOOKINGS FROM SCHEDULE
========================================================= */

function syncBookingsFromSchedule(
  payload
) {
  const existing =
    new Map(
      state.bookings.map(
        (b) => [
          String(b.date),
          b,
        ]
      )
    );

  const next = [];

  for (
    const day
    of payload.by_day || []
  ) {
    const shortage =
      Number(day.shortage || 0);

    if (shortage <= 0) {
      continue;
    }

    const old =
      existing.get(
        String(day.date)
      );

    next.push({
      id:
        old?.id ||
        `booking-${day.date}`,

      date: day.date,

      required_people:
        Number(
          day.required_people || 0
        ),

      available_people:
        Number(
          day.working_count || 0
        ),

      shortage,

      status:
        old?.status ||
        "needed",

      booked_by:
        old?.booked_by ||
        "",

      comment:
        old?.comment ||
        "",
    });
  }

  state.bookings = next;

  saveLocalState();

  renderBookings();
}


/* =========================================================
   DAY VIEW
========================================================= */

function openDayView(dateIso) {
  if (!state.schedule) return;

  const day =
    (state.schedule.by_day || [])
      .find(
        (d) =>
          d.date === dateIso
      );

  if (!day) return;

  state.selectedDay = dateIso;

  $("#days-view")
    .classList
    .add("hidden");

  $("#day-view")
    .classList
    .remove("hidden");

  $("#day-view-title").textContent =
    `${fmtDate(day.date)} · ${day.weekday_name}`;

  const shortage =
    Number(day.shortage || 0);

  const booking =
    state.bookings.find(
      (b) =>
        b.date === day.date
    );

  const booked =
    booking?.status === "booked";

  $("#day-view-meta").textContent =
    `На смене: ${day.working_count} / нужно: ${day.required_people}` +
    (
      shortage > 0
        ? ` · мало на ${shortage}`
        : ""
    ) +
    (
      booked
        ? ` · бронь: ${booking.booked_by ||
        "указана"
        }`
        : ""
    );

  if (shortage > 0) {
    $("#day-view-booking").innerHTML = `
      <button
        type="button"
        class="btn ${booked ? "" : "primary"
      }"
        data-book-day="${booking?.id || ""}"
        data-book-status="${booked ? "booked" : "needed"
      }"
      >
        ${booked
        ? "Снять бронь"
        : "Забронировать этот день"
      }
      </button>
    `;
  } else {
    $("#day-view-booking").innerHTML = `
      <p
        class="hint"
        style="margin:0"
      >
        Людей хватает — бронировать не нужно
      </p>
    `;
  }

  const people =
    peopleForDay(dateIso);

  if (!people.length) {
    $("#day-view-axis").innerHTML = "";
    $("#day-view-timeline").innerHTML = "";
    $("#day-hours-wrap").innerHTML = "";

    $("#day-view-list").innerHTML = `
      <div class="empty">
        В этот день никто не работает
      </div>
    `;

    return;
  }

  $("#day-view-axis").innerHTML = `
    <span>00</span>
    <span>04</span>
    <span>08</span>
    <span>12</span>
    <span>16</span>
    <span>20</span>
    <span>24</span>
  `;

  $("#day-view-timeline").innerHTML =
    people
      .map((p, idx) => {
        const start =
          Math.max(
            0,
            Math.min(
              p.startMin ?? 0,
              24 * 60
            )
          );

        const endRaw =
          p.endMin ??
          start + 60;

        const end =
          Math.max(
            start + 30,
            Math.min(
              endRaw,
              24 * 60
            )
          );

        const left =
          (start /
            (24 * 60)) *
          100;

        const width =
          Math.max(
            ((end - start) /
              (24 * 60)) *
            100,
            4
          );

        const overnight =
          (p.endMin ?? 0) >
          24 * 60;

        const label =
          overnight
            ? `${p.name} ${p.time} (до ночи+)`
            : `${p.name} ${p.time}`;

        const top =
          8 +
          (idx % 2) * 28;

        return `
          <div
            class="timeline-bar"
            style="
              left:${left}%;
              width:${width}%;
              top:${top}px
            "
            title="${escapeHtml(
          label
        )}"
          >
            ${escapeHtml(
          p.name
        )}
          </div>
        `;
      })
      .join("");

  $("#day-hours-wrap")
    .innerHTML =
    buildHourTable(people);

  $("#day-view-list")
    .innerHTML =
    people
      .map(
        (p) => `
          <div class="time-card">
            <div>
              <div class="who">
                ${escapeHtml(
          p.name
        )}
              </div>

              <div class="meta">
                ${p.time
            ? "смена"
            : "время не указано"
          }
              </div>
            </div>

            <div class="when">
              ${p.time
            ? escapeHtml(
              p.time
            )
            : "—"
          }
            </div>
          </div>
        `
      )
      .join("");
}


$("#btn-back-days").addEventListener(
  "click",
  showDaysView
);


/* =========================================================
   MONTH DAYS
========================================================= */

function renderMonthDays(
  payload
) {
  const grid =
    $("#month-days-grid");

  grid.innerHTML =
    (payload.by_day || [])
      .map((d) => {
        const shortage =
          Number(
            d.shortage || 0
          );

        const booking =
          state.bookings.find(
            (b) =>
              b.date === d.date
          );

        const booked =
          booking?.status ===
          "booked";

        const cls = [
          "month-day",
          shortage > 0
            ? "has-shortage"
            : "",
          booked
            ? "is-booked"
            : "",
          state.selectedDay ===
            d.date
            ? "selected"
            : "",
        ]
          .filter(Boolean)
          .join(" ");

        return `
          <button
            type="button"
            class="${cls}"
            data-open-day="${d.date}"
          >
            <div class="day-num">
              ${d.day}
            </div>

            <div class="day-wd">
              ${d.weekday_name}
            </div>

            <div class="day-count">
              ${d.working_count} чел.
            </div>

            <div class="meta">
              ${booked
            ? "бронь"
            : shortage > 0
              ? `мало −${shortage}`
              : "открыть"
          }
            </div>
          </button>
        `;
      })
      .join("");
}


/* =========================================================
   FULL SCHEDULE RENDER
========================================================= */

function renderSchedule(
  payload
) {
  state.schedule =
    payload;

  setMonthPicker(
    payload.year,
    payload.month
  );

  $("#schedule-meta").textContent =
    `Собрано: ${payload.generated_at
    } · людей: ${payload.people.length
    } · дней с дефицитом: ${payload.summary
      ?.days_with_shortage ??
    0
    }`;

  $("#btn-xlsx").href =
    `/api/schedule/${payload.year
    }/${payload.month
    }/xlsx`;

  syncBookingsFromSchedule(
    payload
  );

  renderMonthDays(
    payload
  );

  const byDate =
    Object.fromEntries(
      (payload.by_day || [])
        .map((d) => [
          d.date,
          d,
        ])
    );

  const headDays =
    payload.days
      .map((d) => {
        const info =
          byDate[d.date] ||
          {};

        const shortage =
          Number(
            info.shortage || 0
          );

        const booking =
          state.bookings.find(
            (b) =>
              b.date ===
              d.date
          );

        const booked =
          booking?.status ===
          "booked";

        const mark =
          shortage > 0
            ? `
              <div
                class="th-book-mark"
              >
                ${booked
              ? "бронь"
              : "−" +
              shortage
            }
              </div>
            `
            : "";

        return `
          <th
            data-open-day="${d.date}"
            class="clickable-day"
            title="Открыть день"
          >
            <div>
              ${d.day}
            </div>

            <div
              style="opacity:.6"
            >
              ${d.weekday_name}
            </div>

            ${mark}
          </th>
        `;
      })
      .join("");

  const body =
    payload.people
      .map((p) => {
        const cells =
          p.cells
            .map((c) => {
              const info =
                byDate[c.date] ||
                {};

              const shortage =
                Number(
                  info.shortage ||
                  0
                );

              const booking =
                state.bookings.find(
                  (b) =>
                    b.date ===
                    c.date
                );

              const booked =
                booking?.status ===
                "booked";

              let cls =
                c.status ===
                  "work"
                  ? "cell-work"
                  : c.status ===
                    "vacation"
                    ? "cell-vacation"
                    : "cell-off";

              if (
                shortage > 0
              ) {
                cls += booked
                  ? " cell-day-booked"
                  : " cell-day-shortage";
              }

              let mark = "·";

              if (
                c.status ===
                "vacation"
              ) {
                mark = "О";
              } else if (
                c.status ===
                "work"
              ) {
                mark =
                  c.time
                    ? `<span class="cell-time">${escapeHtml(
                      c.time
                    )}</span>`
                    : "●";
              }

              return `
                <td
                  class="${cls}"
                  data-open-day="${c.date}"
                  title="Открыть ${c.date}"
                >
                  ${mark}
                </td>
              `;
            })
            .join("");

        return `
          <tr>
            <td>
              <strong>
                ${escapeHtml(
          p.name
        )}
              </strong>

              <br/>

              <span class="meta">
                ${escapeHtml(
          patternLabel(p)
        )}
                ·
                р${p.stats.work}
                /
                о${p.stats.off}
                /
                отп${p.stats.vacation}
              </span>
            </td>

            ${cells}
          </tr>
        `;
      })
      .join("");

  $("#schedule-table")
    .innerHTML = `
      <table class="schedule">
        <thead>
          <tr>
            <th>
              Сотрудник
            </th>

            ${headDays}
          </tr>
        </thead>

        <tbody>
          ${body ||
    `
              <tr>
                <td
                  colspan="${payload.days.length + 1
    }"
                  class="empty"
                >
                  Нет сотрудников
                </td>
              </tr>
            `
    }
        </tbody>
      </table>
    `;

  if (
    state.selectedDay &&
    payload.by_day.some(
      (d) =>
        d.date ===
        state.selectedDay
    )
  ) {
    openDayView(
      state.selectedDay
    );
  } else {
    showDaysView();
  }
}


/* =========================================================
   SCHEDULE EVENTS
========================================================= */

$("#panel-schedule")
  .addEventListener(
    "click",
    (ev) => {
      const bookBtn =
        ev.target.closest(
          "[data-book-day]"
        );

      if (bookBtn) {
        const booking =
          state.bookings.find(
            (b) =>
              String(b.id) ===
              String(
                bookBtn.dataset
                  .bookDay
              )
          );

        if (!booking) {
          toast(
            "Для этого дня бронь ещё не создана"
          );

          return;
        }

        const next =
          booking.status ===
            "booked"
            ? "needed"
            : "booked";

        const bookedBy =
          next === "booked"
            ? getBookingUserName()
            : "";

        if (
          next === "booked" &&
          !bookedBy
        ) {
          toast(
            "Имя не указано, бронь не поставлена"
          );

          return;
        }

        updateBooking(
          booking.id,
          next,
          bookedBy
        );

        openDayView(
          state.selectedDay
        );

        return;
      }

      const dayBtn =
        ev.target.closest(
          "[data-open-day]"
        );

      if (dayBtn) {
        openDayView(
          dayBtn.dataset
            .openDay
        );
      }
    }
  );


/* =========================================================
   GENERATION
========================================================= */

async function generate(
  opts
) {
  try {
    const payload =
      await api(
        "/api/schedule/generate",
        {
          method: "POST",

          body: JSON.stringify(
            opts
          ),
        }
      );

    renderSchedule(
      payload
    );

    switchTab(
      "schedule"
    );

  } catch (e) {
    toast(
      e.message,
      true
    );
  }
}

function showConfirmModal({
  title = "Подтверждение",
  text = "",
  confirmText = "Подтвердить",
  danger = true,
}) {
  return new Promise((resolve) => {
    const modal = $("#confirm-modal");
    const titleEl = $("#confirm-title");
    const textEl = $("#confirm-text");
    const okBtn = $("#confirm-ok");
    const cancelBtn = $("#confirm-cancel");

    titleEl.textContent = title;
    textEl.textContent = text;
    okBtn.textContent = confirmText;

    okBtn.classList.toggle("btn-danger", danger);

    modal.classList.remove("hidden");

    const close = (result) => {
      modal.classList.add("hidden");

      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);

      resolve(result);
    };

    const onOk = () => close(true);
    const onCancel = () => close(false);

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
  });
}

async function rebuildAndShowSchedule() {
  const val =
    $("#month-picker")?.value;

  if (val) {
    const [y, m] =
      val
        .split("-")
        .map(Number);

    await generate({
      next_month: false,
      year: y,
      month: m,
    });

    return;
  }

  await generate({
    next_month: true,
  });
}


async function reloadCurrentSchedule(
  switchToSchedule = true
) {
  if (!state.schedule) {
    return;
  }

  const payload =
    await api(
      "/api/schedule/generate",
      {
        method: "POST",

        body: JSON.stringify({
          next_month: false,

          year:
            state.schedule.year,

          month:
            state.schedule.month,
        }),
      }
    );

  renderSchedule(
    payload
  );

  if (switchToSchedule) {
    switchTab(
      "schedule"
    );
  }
}


async function refreshScheduleIfLoaded() {
  if (!state.schedule) {
    return;
  }

  await reloadCurrentSchedule(
    false
  );
}


$("#btn-gen-next")
  .addEventListener(
    "click",
    () =>
      generate({
        next_month: true,
      })
  );


$("#btn-gen-current")
  .addEventListener(
    "click",
    () => {
      const now =
        new Date();

      generate({
        next_month: false,

        year:
          now.getFullYear(),

        month:
          now.getMonth() + 1,
      });
    }
  );


$("#month-picker")
  .addEventListener(
    "change",
    async () => {
      const val =
        $("#month-picker")
          .value;

      if (!val) return;

      const [y, m] =
        val
          .split("-")
          .map(Number);

      try {
        const payload =
          await api(
            "/api/schedule/generate",
            {
              method: "POST",

              body:
                JSON.stringify({
                  next_month: false,
                  year: y,
                  month: m,
                }),
            }
          );

        renderSchedule(
          payload
        );

      } catch (e) {
        toast(
          e.message,
          true
        );
      }
    }
  );


/* =========================================================
   INIT
========================================================= */

function initMonthPicker() {
  const now =
    new Date();

  let y =
    now.getFullYear();

  let m =
    now.getMonth() + 2;

  if (m > 12) {
    m = 1;
    y += 1;
  }

  setMonthPicker(
    y,
    m
  );
}


(async function init() {
  try {
    initMonthPicker();

    await loadAccounts();

    await loadVacations();

    loadDemand();

    try {
      const val =
        $("#month-picker")
          .value;

      const [y, m] =
        val
          .split("-")
          .map(Number);

      const payload =
        await api(
          `/api/schedule/${y}/${m}`
        );

      renderSchedule(
        payload
      );
    } catch (_) {
      // Графика ещё нет — это нормально.
    }

    renderBookings();

  } catch (e) {
    console.error(e);

    toast(
      `Ошибка загрузки: ${e.message}`,
      true
    );
  }
})();
